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
            "SELECT id FROM songs WHERE track_id = %s",
            (request.track_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(404, "Track not found in database")

        cursor.execute(
            "INSERT INTO feedback (track_id, action) VALUES (%s, %s)",
            (request.track_id, request.action)
        )

        if request.action == "accept":
            cursor.execute("""
                INSERT INTO graph_nodes (track_id, is_seed)
                VALUES (%s, true)
                ON CONFLICT (track_id) DO UPDATE SET is_seed = true
            """, (request.track_id,))

            cursor.execute(
                "SELECT source_id, similarity FROM graph_edges WHERE target_id = %s LIMIT 1",
                (request.track_id,)
            )
            parent = cursor.fetchone()
            if parent:
                cursor.execute("""
                    INSERT INTO graph_edges (source_id, target_id, similarity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_id, target_id) DO UPDATE SET similarity = EXCLUDED.similarity
                """, (parent["source_id"], request.track_id, parent["similarity"]))

            cursor.execute(
                "SELECT embedding FROM songs WHERE track_id = %s",
                (request.track_id,)
            )
            song_row = cursor.fetchone()
            if song_row and song_row["embedding"] is not None:
                base_embedding = list(song_row["embedding"])
                steered = steering.apply_steering(base_embedding, request.track_id)

                cursor.execute("""
                    SELECT track_id, 1 - (embedding <=> %s::vector) AS similarity
                    FROM songs
                    WHERE embedding IS NOT NULL
                    AND listeners < %s
                    AND track_id != %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (steered, MAX_LISTENERS, request.track_id, steered, DEFAULT_K))

                for r in cursor.fetchall():
                    cursor.execute("""
                        INSERT INTO graph_edges (source_id, target_id, similarity)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (source_id, target_id) DO UPDATE SET similarity = EXCLUDED.similarity
                    """, (request.track_id, r["track_id"], r["similarity"]))

    return FeedbackResponse(
        success=True,
        message=f"Track {request.action}ed successfully"
    )
