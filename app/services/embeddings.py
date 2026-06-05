import hashlib
import numpy as np
from app.db import get_cursor
from app.config import EMBEDDING_DIM, MAX_LISTENERS, DEFAULT_K


def make_track_id(artist: str, track: str) -> str:
    key = f"{artist.strip().lower()}|||{track.strip().lower()}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


"""
    takes a list of tag strings and upserts them into the tag_vocab table, this is how our vocab grows over time
"""
def get_or_create_tag_ids(tags: list[str]) -> dict[str, int]:
    tag_ids = {}
    with get_cursor() as cursor:
        for tag in tags:
            # SELECT first so existing tags don't consume a SERIAL value. The old
            # `INSERT ... ON CONFLICT DO UPDATE` burned a sequence id on EVERY call
            # (Postgres allocates one even when the insert conflicts), so ids raced
            # far past the row count and past EMBEDDING_DIM — and build_tag_vector
            # silently drops any tag whose id >= EMBEDDING_DIM. Only genuinely-new
            # tags should claim an id.
            cursor.execute("SELECT id FROM tag_vocab WHERE tag = %s", (tag,))
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "INSERT INTO tag_vocab (tag) VALUES (%s) ON CONFLICT (tag) DO NOTHING RETURNING id",
                    (tag,),
                )
                row = cursor.fetchone()
                if row is None:
                    # lost a race to a concurrent insert — read the winner's id
                    cursor.execute("SELECT id FROM tag_vocab WHERE tag = %s", (tag,))
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


def ann_search(
    embedding: list,
    *,
    listeners_cap: int = MAX_LISTENERS,
    exclude_ids=(),
    allowed_ids=None,
    limit: int = DEFAULT_K,
    cursor=None,
) -> list[dict]:
    """
    Approximate-nearest-neighbor search over the songs table — the single source
    of truth for vector lookups used by seeding, recommendations and playlists.

    Returns songs ordered by cosine distance to `embedding`, filtered to those
    under `listeners_cap`, never including `exclude_ids`, and (if `allowed_ids` is
    a non-empty set) restricted to that set. Pass an open `cursor` to reuse a
    transaction; otherwise one is opened for the query.
    """
    use_allowed = bool(allowed_ids)
    allowed_clause = "AND track_id = ANY(%s)" if use_allowed else ""
    sql = f"""
        SELECT track_id, name, artist, listeners, image, embedding,
               1 - (embedding <=> %s::vector) AS similarity
        FROM songs
        WHERE embedding IS NOT NULL
          AND listeners < %s
          AND track_id != ALL(%s)
          {allowed_clause}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    params = [embedding, listeners_cap, list(exclude_ids)]
    if use_allowed:
        params.append(list(allowed_ids))
    params += [embedding, limit]

    def _run(cur) -> list[dict]:
        cur.execute(sql, params)
        return [
            {
                "track_id": r["track_id"],
                "name": r["name"],
                "artist": r["artist"],
                "listeners": r["listeners"],
                "image": r["image"],
                "embedding": [float(x) for x in r["embedding"]],
                "similarity": round(r["similarity"], 3),
            }
            for r in cur.fetchall()
        ]

    if cursor is not None:
        return _run(cursor)
    with get_cursor() as cur:
        return _run(cur)


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


def dominant_tags(vectors: list[list], id_to_tag: dict[int, str], top_n: int = 15) -> list[dict]:
    """
    Aggregate the dominant tags across a set of song embeddings (e.g. every node
    in a graph) so the UI can show which genres are taking over.

    Each embedding slot `i` corresponds to tag_vocab id `i` (build_tag_vector
    writes a tag's normalized 0..1 weight into slot == its vocab id). We sum those
    weights per slot across all vectors; the result is the tag's total presence in
    the graph. `count` is how many songs carry the tag, and `share` is the tag's
    fraction of the summed weight (a rough "% of the vibe"). Returns the top `top_n`
    by weight, descending.
    """
    if not vectors:
        return []

    weight: dict[int, float] = {}
    count: dict[int, int] = {}
    for vec in vectors:
        for i, x in enumerate(vec):
            if x > 0:
                weight[i] = weight.get(i, 0.0) + x
                count[i] = count.get(i, 0) + 1

    total = sum(weight.values()) or 1.0
    rows = [
        {
            "tag": id_to_tag[i],
            "weight": round(w, 4),
            "count": count[i],
            "share": round(w / total, 4),
        }
        for i, w in weight.items()
        if i in id_to_tag
    ]
    rows.sort(key=lambda r: r["weight"], reverse=True)
    return rows[:top_n]


def mmr_rerank(query_embedding: list, candidates: list[dict], k: int, lambda_param: float) -> list[dict]:
    """
    Maximal Marginal Relevance re-ranking. Each candidate dict must have an 'embedding' key.
    Balances similarity to the query (relevance) against similarity to already-selected items (diversity).
    """
    if not candidates:
        return []

    selected = []
    remaining = candidates[:]

    while len(selected) < k and remaining:
        best = None
        best_score = float("-inf")

        for candidate in remaining:
            relevance = cosine_similarity(query_embedding, candidate["embedding"])
            redundancy = max(
                (cosine_similarity(candidate["embedding"], s["embedding"]) for s in selected),
                default=0.0,
            )
            score = lambda_param * relevance - (1 - lambda_param) * redundancy

            if score > best_score:
                best_score = score
                best = candidate

        selected.append(best)
        remaining.remove(best)

    return selected