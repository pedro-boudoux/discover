from fastapi import APIRouter, Query, HTTPException
from app.models import SongSearchResult, TrackFeatures
from app.services import spotify, lastfm, embeddings as emb_service
from app.db import get_cursor
from app.config import EMBEDDING_DIM

router = APIRouter(prefix="/songs", tags=["songs"])


@router.get("/search", response_model=list[SongSearchResult])
def search_songs(q: str = Query(..., min_length=1)):
    return spotify.search_songs(q)


@router.get("/{spotify_id}/features", response_model=TrackFeatures)
def get_song_features(spotify_id: str):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT name, artist, listeners, embedding FROM songs WHERE spotify_id = %s",
            (spotify_id,)
        )
        row = cursor.fetchone()
        if row:
            embedding = list(row["embedding"]) if row["embedding"] else []
            tags = []
            if embedding:
                cursor.execute("SELECT id, tag FROM tag_vocab WHERE id < %s", (EMBEDDING_DIM,))
                tags = [
                    r["tag"] for r in cursor.fetchall()
                    if r["id"] < len(embedding) and embedding[r["id"]] > 0
                ]
            return TrackFeatures(
                spotify_id=spotify_id,
                name=row["name"],
                artist=row["artist"],
                listeners=row["listeners"] or 0,
                tags=tags,
                embedding=embedding or None
            )

    track = spotify.get_track(spotify_id)
    lastfm_track = lastfm.get_track_info(track["artist"], track["name"])
    artist_tags = lastfm.get_artist_top_tags(track["artist"])

    tag_counts = {**{t: 50 for t in lastfm_track["tags"][:5]}, **artist_tags}
    emb_service.get_or_create_tag_ids(list(tag_counts.keys()))
    vector = emb_service.build_tag_vector(tag_counts)

    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO songs (spotify_id, name, artist, listeners, image, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (spotify_id) DO UPDATE SET
                listeners = EXCLUDED.listeners,
                image = EXCLUDED.image,
                embedding = EXCLUDED.embedding
        """, (spotify_id, track["name"], track["artist"], lastfm_track["listeners"], track["image"], vector))

    return TrackFeatures(
        spotify_id=spotify_id,
        name=track["name"],
        artist=track["artist"],
        listeners=lastfm_track["listeners"],
        tags=list(tag_counts.keys()),
        embedding=vector
    )
