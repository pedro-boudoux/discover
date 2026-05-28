from fastapi import APIRouter, Query, HTTPException
from app.models import SongSearchResult, TrackFeatures
from app.services import lastfm, embeddings as emb_service
from app.db import get_cursor
from app.config import EMBEDDING_DIM

router = APIRouter(prefix="/songs", tags=["songs"])


"""
    Entry point for the user, takes user's search input and returns a track that matches that query.
    /search?q={USER_INPUT}
"""
@router.get("/search", response_model=list[SongSearchResult])
def search_songs(q: str = Query(..., min_length=1)):

    # gets list of dicts (ea with a name, artist and image) from Last.fm's API
    tracks = lastfm.search_tracks(q)

    # generates our own list of track ids for each song based on the artist+name
    results = []
    for t in tracks:
        track_id = emb_service.make_track_id(t["artist"], t["name"])
        t["track_id"] = track_id
        results.append(t)

    # records that the results exist by inserting them into the songs table
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

    # returns list of song search results
    return [
        SongSearchResult(
            track_id=t["track_id"],
            name=t["name"],
            artist=t["artist"],
            image=t["image"]
        )
        for t in results
    ]


"""
    Lightweight status check — does this song already have an embedding cached?
    Used by the frontend to warn the user about cold seeds (which trigger
    multiple Last.fm calls and take much longer).
"""
@router.get("/{track_id}/status")
def get_song_status(track_id: str):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT embedding FROM songs WHERE track_id = %s",
            (track_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"exists": False, "cached": False}
        return {"exists": True, "cached": row["embedding"] is not None}


"""
    takes a {track_id} (generated in /search), returns the song with embeddings, tags, etc
"""
@router.get("/{track_id}/features", response_model=TrackFeatures)
def get_song_features(track_id: str):
    with get_cursor() as cursor:

        # fetch that track_id in the songs table
        cursor.execute(
            "SELECT name, artist, listeners, embedding FROM songs WHERE track_id = %s",
            (track_id,)
        )
        row = cursor.fetchone()

        # raise exception if dne
        if not row:
            raise HTTPException(404, "Track not found — search for it first")

        # if embedding!=null that means that we've seen this song before (cache hit)
        # we can just return the track
        if row["embedding"] is not None:
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

        # cache miss: we haven't seen this song before and need to generate embeddings for it
        else:
            name = row["name"]
            artist = row["artist"]

            # get listener count + basic track-level tags
            lastfm_track = lastfm.get_track_info(artist, name)

            # get artist tags (background context, downweighted) and track-specific tags (dominant)
            artist_tags = lastfm.get_artist_top_tags(artist)
            track_tags = lastfm.get_track_top_tags(artist, name)
            similar_artists = lastfm.get_similar_artists(artist)
            similar_tags = [(lastfm.get_artist_top_tags(a["artist"]), a["match"]) for a in similar_artists]
            tag_counts = lastfm.blend_tags(artist_tags, track_tags, similar_tags)

            # builds embedding for the track
            emb_service.get_or_create_tag_ids(list(tag_counts.keys()))
            vector = emb_service.build_tag_vector(tag_counts)

            # updates entry in songs table
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
