from fastapi import APIRouter, Query
from app.models import RecommendationsResponse, Recommendation
from app.db import get_cursor
from app.services import steering
from app.config import MAX_LISTENERS, DEFAULT_K

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/{spotify_id}", response_model=RecommendationsResponse)
def get_recommendations(
    spotify_id: str,
    k: int = Query(default=DEFAULT_K, ge=1, le=50)
):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT embedding FROM songs WHERE spotify_id = %s",
            (spotify_id,)
        )
        row = cursor.fetchone()
        if not row or not row["embedding"]:
            return RecommendationsResponse(recommendations=[])

        base_embedding = list(row["embedding"])
        steered_embedding = steering.apply_steering(base_embedding, spotify_id)

        cursor.execute("""
            SELECT spotify_id, name, artist, listeners, image,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM songs
            WHERE embedding IS NOT NULL
            AND listeners < %s
            AND spotify_id != %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (steered_embedding, MAX_LISTENERS, spotify_id, steered_embedding, k))

        recommendations = [
            Recommendation(
                spotify_id=r["spotify_id"],
                name=r["name"],
                artist=r["artist"],
                similarity=round(r["similarity"], 3),
                listeners=r["listeners"],
                image=r["image"]
            )
            for r in cursor.fetchall()
        ]

    return RecommendationsResponse(recommendations=recommendations)
