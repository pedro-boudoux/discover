from fastapi import APIRouter, HTTPException
from app.models import FeedbackRequest, FeedbackResponse
from app.db import get_cursor
from app.services import steering
from app.config import MAX_LISTENERS, DEFAULT_K

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse)
def submit_feedback(request: FeedbackRequest):
    if request.action not in ("accept", "reject"):
        raise HTTPException(400, "Action must be 'accept' or 'reject'")

    with get_cursor() as cursor:
        cursor.execute(
            "SELECT id FROM songs WHERE spotify_id = %s",
            (request.spotify_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(404, "Song not found in database")

        cursor.execute(
            "INSERT INTO feedback (spotify_id, action) VALUES (%s, %s)",
            (request.spotify_id, request.action)
        )

        if request.action == "accept":
            cursor.execute("""
                INSERT INTO graph_nodes (spotify_id, is_seed)
                VALUES (%s, true)
                ON CONFLICT (spotify_id) DO UPDATE SET is_seed = true
            """, (request.spotify_id,))

            # Preserve the edge from the parent that recommended this song
            cursor.execute(
                "SELECT source_id, similarity FROM graph_edges WHERE target_id = %s LIMIT 1",
                (request.spotify_id,)
            )
            parent = cursor.fetchone()
            if parent:
                cursor.execute("""
                    INSERT INTO graph_edges (source_id, target_id, similarity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_id, target_id) DO UPDATE SET similarity = EXCLUDED.similarity
                """, (parent["source_id"], request.spotify_id, parent["similarity"]))

            # Run ANN search from the newly accepted seed and write its edges
            cursor.execute(
                "SELECT embedding FROM songs WHERE spotify_id = %s",
                (request.spotify_id,)
            )
            song_row = cursor.fetchone()
            if song_row and song_row["embedding"]:
                base_embedding = list(song_row["embedding"])
                steered = steering.apply_steering(base_embedding, request.spotify_id)

                cursor.execute("""
                    SELECT spotify_id, 1 - (embedding <=> %s::vector) AS similarity
                    FROM songs
                    WHERE embedding IS NOT NULL
                    AND listeners < %s
                    AND spotify_id != %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (steered, MAX_LISTENERS, request.spotify_id, steered, DEFAULT_K))

                for r in cursor.fetchall():
                    cursor.execute("""
                        INSERT INTO graph_edges (source_id, target_id, similarity)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (source_id, target_id) DO UPDATE SET similarity = EXCLUDED.similarity
                    """, (request.spotify_id, r["spotify_id"], r["similarity"]))

    return FeedbackResponse(
        success=True,
        message=f"Song {request.action}ed successfully"
    )
