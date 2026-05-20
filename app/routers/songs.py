from fastapi import APIRouter, Query, HTTPException
from app.models import SongSearchResult, TrackFeatures
from app.services import lastfm, embeddings as emb_service
from app.db import get_cursor
from app.config import EMBEDDING_DIM

router = APIRouter(prefix="/songs", tags=["songs"])


@router.get("/search", response_model=list[SongSearchResult])
def search_songs(q: str = Query(..., min_length=1)):
    tracks = lastfm.search_tracks(q)
    results = []
    for t in tracks:
        track_id = emb_service.make_track_id(t["artist"], t["name"])
        t["track_id"] = track_id
        results.append(t)

    with get_cursor() as cursor:
        for t in results:
            cursor.execute("""
                INSERT INTO songs (track_id, name, artist, image)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (track_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    artist = EXCLUDED.artist,
                    image = EXCLUDED.image
            """, (t["track_id"], t["name"], t["artist"], t["image"]))

    return [
        SongSearchResult(
            track_id=t["track_id"],
            name=t["name"],
            artist=t["artist"],
            image=t["image"]
        )
        for t in results
    ]


@router.get("/{track_id}/features", response_model=TrackFeatures)
def get_song_features(track_id: str):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT name, artist, listeners, embedding FROM songs WHERE track_id = %s",
            (track_id,)
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(404, "Track not found — search for it first")

        if row["embedding"]:
            embedding = list(row["embedding"])
            cursor.execute("SELECT id, tag FROM tag_vocab WHERE id < %s", (EMBEDDING_DIM,))
            tags = [
                r["tag"] for r in cursor.fetchall()
                if r["id"] < len(embedding) and embedding[r["id"]] > 0
            ]
            return TrackFeatures(
                track_id=track_id,
                name=row["name"],
                artist=row["artist"],
                listeners=row["listeners"] or 0,
                tags=tags,
                embedding=embedding
            )

        name = row["name"]
        artist = row["artist"]

    lastfm_track = lastfm.get_track_info(artist, name)
    artist_tags = lastfm.get_artist_top_tags(artist)
    tag_counts = {**{t: 50 for t in lastfm_track["tags"][:5]}, **artist_tags}
    emb_service.get_or_create_tag_ids(list(tag_counts.keys()))
    vector = emb_service.build_tag_vector(tag_counts)

    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE songs SET listeners = %s, embedding = %s WHERE track_id = %s
        """, (lastfm_track["listeners"], vector, track_id))

    return TrackFeatures(
        track_id=track_id,
        name=name,
        artist=artist,
        listeners=lastfm_track["listeners"],
        tags=list(tag_counts.keys()),
        embedding=vector
    )
