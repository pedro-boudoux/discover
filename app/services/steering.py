import numpy as np
from app.db import get_cursor
from app.config import STEERING_ALPHA


def get_rejected_embeddings(seed_spotify_id: str) -> list:
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT s.embedding
            FROM feedback f
            JOIN songs s ON f.spotify_id = s.spotify_id
            WHERE f.action = 'reject'
            AND EXISTS (
                SELECT 1 FROM graph_edges ge
                WHERE ge.source_id = %s AND ge.target_id = f.spotify_id
            )
        """, (seed_spotify_id,))
        results = cursor.fetchall()
        return [list(row["embedding"]) for row in results if row["embedding"]]


def apply_steering(base_embedding: list, seed_spotify_id: str) -> list:
    base = np.array(base_embedding)
    rejected = get_rejected_embeddings(seed_spotify_id)

    if not rejected:
        return base.tolist()

    steering = np.zeros_like(base)
    for rej in rejected:
        rej_vec = np.array(rej)
        steering += STEERING_ALPHA * rej_vec

    result = base - steering
    norm = np.linalg.norm(result)
    result = result / norm if norm > 0 else result

    return result.tolist()