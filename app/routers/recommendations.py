from fastapi import APIRouter, Query
from app.models import RecommendationsResponse, Recommendation
from app.db import get_cursor
from app.services import steering
from app.services.embeddings import mmr_rerank
from app.config import MAX_LISTENERS, DEFAULT_K, MMR_LAMBDA, MMR_POOL_MULTIPLIER, MMR_MAX_PER_ARTIST

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/{track_id}", response_model=RecommendationsResponse)
def get_recommendations(
    track_id: str,
    k: int = Query(default=DEFAULT_K, ge=1, le=50),
    lambda_param: float = Query(default=MMR_LAMBDA, ge=0.0, le=1.0, alias="lambda"),
    exclude: list[str] = Query(default=[])
):
    with get_cursor() as cursor:

        cursor.execute(
            "SELECT embedding FROM songs WHERE track_id = %s",
            (track_id,)
        )
        row = cursor.fetchone()

        # if song somehow doesn't have an embedding we send empty recs
        # TODO: I should make it so that this makes embeddings for said song, but I don't know how this will be used in the frontend yet so I'll wait.
        if not row or row["embedding"] is None:
            return RecommendationsResponse(recommendations=[])

        base_embedding = list(row["embedding"])
        steered_embedding = steering.apply_steering(base_embedding, track_id)

        exclude_ids = list({track_id, *exclude})
        cursor.execute("""
            SELECT track_id, name, artist, listeners, image, embedding,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM songs
            WHERE embedding IS NOT NULL
            AND listeners < %s
            AND track_id != ALL(%s)
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (steered_embedding, MAX_LISTENERS, exclude_ids, steered_embedding, k * MMR_POOL_MULTIPLIER))

        pool = [
            {
                "track_id": r["track_id"],
                "name": r["name"],
                "artist": r["artist"],
                "listeners": r["listeners"],
                "image": r["image"],
                "embedding": list(r["embedding"]),
                "similarity": round(r["similarity"], 3),
            }
            for r in cursor.fetchall()
        ]

    artist_counts: dict[str, int] = {}
    capped_pool = []
    for candidate in pool:
        artist = str(candidate["artist"])
        if artist_counts.get(artist, 0) < MMR_MAX_PER_ARTIST:
            capped_pool.append(candidate)
            artist_counts[artist] = artist_counts.get(artist, 0) + 1

    reranked = mmr_rerank(steered_embedding, capped_pool, k, lambda_param)

    recommendations = [
        Recommendation(
            track_id=r["track_id"],
            name=r["name"],
            artist=r["artist"],
            similarity=r["similarity"],
            listeners=r["listeners"],
            image=r["image"],
        )
        for r in reranked
    ]

    return RecommendationsResponse(recommendations=recommendations)
