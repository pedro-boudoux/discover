import numpy as np
from app.db import get_cursor
from app.config import EMBEDDING_DIM


"""
    takes a list of tag strings and upserts them into the tag_vocab table, this is how our vocab grows over time
"""
def get_or_create_tag_ids(tags: list[str]) -> dict[str, int]:
    tag_ids = {}
    with get_cursor() as cursor:
        for tag in tags:
            cursor.execute("""
                INSERT INTO tag_vocab (tag) VALUES (%s)
                ON CONFLICT (tag) DO UPDATE SET tag = EXCLUDED.tag
                RETURNING id
            """, (tag,))
            row = cursor.fetchone()
            tag_ids[tag] = row["id"]
    return tag_ids


"""
    takes the {tag : count} dict from get_artist_top_tags, looks up each tag's position in the vocab, normalizes counts to 0-1 and places them into a fixed-size float array of length EMBEDDING_DIM. 

    tags not in the vocab yet are ignored (they need get_or_create_tag_ids called first)

    this vector is what gets stored in pgvector and queried for ANN search
"""
def build_tag_vector(tag_counts: dict[str, int]) -> list[float]:
    if not tag_counts:
        return [0.0] * EMBEDDING_DIM

    with get_cursor() as cursor:
        cursor.execute("SELECT id, tag FROM tag_vocab")
        vocab = {row["tag"]: row["id"] for row in cursor.fetchall()}

    max_count = max(tag_counts.values()) if tag_counts else 1

    vector = [0.0] * EMBEDDING_DIM
    for tag, count in tag_counts.items():
        if tag in vocab and vocab[tag] < EMBEDDING_DIM:
            vector[vocab[tag]] = count / max_count

    return vector


"""
    manual cos similarity between two vectors, used for in-memory similarity checks rather than hitting the DB
"""
def cosine_similarity(a: list, b: list) -> float:
    a = np.array(a)
    b = np.array(b)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))