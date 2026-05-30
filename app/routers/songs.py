from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Query, HTTPException
from app.models import SongSearchResult, TrackFeatures
from app.services import lastfm, embeddings as emb_service
from app.services.covers import get_cover_url, is_broken_image
from app.db import get_cursor
from app.config import EMBEDDING_DIM

router = APIRouter(prefix="/songs", tags=["songs"])


SEARCH_LIMIT = 15
LOCAL_SEARCH_LIMIT = 20


def _search_local_songs(q: str, limit: int = LOCAL_SEARCH_LIMIT) -> list[dict]:
    pattern = f"%{q}%"
    prefix = f"{q}%"
    with get_cursor() as cursor:
        cursor.execute(
            """
            SELECT track_id, name, artist, image
            FROM songs
            WHERE name ILIKE %s OR artist ILIKE %s
            ORDER BY
                CASE
                    WHEN name ILIKE %s THEN 0
                    WHEN artist ILIKE %s THEN 1
                    ELSE 2
                END,
                length(name)
            LIMIT %s
            """,
            (pattern, pattern, prefix, prefix, limit),
        )
        rows = cursor.fetchall()
    return [
        {
            "track_id": r["track_id"],
            "name": r["name"],
            "artist": r["artist"],
            "image": r["image"],
        }
        for r in rows
    ]


def _fetch_cached_images(track_ids: list[str]) -> dict[str, str | None]:
    if not track_ids:
        return {}
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT track_id, image FROM songs WHERE track_id = ANY(%s)",
            (track_ids,),
        )
        return {r["track_id"]: r["image"] for r in cursor.fetchall()}


def _upsert_songs(tracks: list[dict]) -> None:
    if not tracks:
        return
    rows = [(t["track_id"], t["name"], t["artist"], t.get("image")) for t in tracks]
    with get_cursor() as cursor:
        # COALESCE preserves a previously-cached real cover when the latest
        # lookup returns nothing, so we never regress a known image to NULL.
        cursor.executemany(
            """
            INSERT INTO songs (track_id, name, artist, image)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (track_id) DO UPDATE SET
                name   = EXCLUDED.name,
                artist = EXCLUDED.artist,
                image  = COALESCE(EXCLUDED.image, songs.image)
            """,
            rows,
        )


"""
    Entry point for the user, takes user's search input and returns a track that matches that query.
    Runs a local DB search and Last.fm search in parallel, merges them, then only fetches
    covers from Deezer / iTunes for tracks we don't already have a real cover for.
    /search?q={USER_INPUT}
"""
@router.get("/search", response_model=list[SongSearchResult])
def search_songs(q: str = Query(..., min_length=1)):

    # Local DB lookup + Last.fm search run concurrently
    with ThreadPoolExecutor(max_workers=2) as pool:
        local_future = pool.submit(_search_local_songs, q)
        lastfm_future = pool.submit(lastfm.search_tracks, q)
        local_tracks = local_future.result()
        lastfm_tracks = lastfm_future.result()

    # Assign track_ids to Last.fm results
    for t in lastfm_tracks:
        t["track_id"] = emb_service.make_track_id(t["artist"], t["name"])

    # Merge: Last.fm first (popularity-ranked), then any local-only matches
    seen: set[str] = set()
    merged: list[dict] = []
    for t in lastfm_tracks:
        if t["track_id"] in seen:
            continue
        seen.add(t["track_id"])
        merged.append({
            "track_id": t["track_id"],
            "name": t["name"],
            "artist": t["artist"],
            "image": t.get("image"),
        })
    for t in local_tracks:
        if t["track_id"] in seen:
            continue
        seen.add(t["track_id"])
        merged.append(t)

    merged = merged[:SEARCH_LIMIT]

    # Reuse cached covers: only call Deezer/iTunes for tracks without a real one
    cached_images = _fetch_cached_images([t["track_id"] for t in merged])
    need_cover: list[dict] = []
    for t in merged:
        cached = cached_images.get(t["track_id"])
        if cached and not is_broken_image(cached):
            t["image"] = cached
        elif is_broken_image(t.get("image")):
            need_cover.append(t)

    if need_cover:
        with ThreadPoolExecutor(max_workers=8) as pool:
            covers = list(
                pool.map(lambda t: get_cover_url(t["artist"], t["name"]), need_cover)
            )
        for t, cover in zip(need_cover, covers):
            t["image"] = cover  # cover may be None — that's fine

    _upsert_songs(merged)

    return [
        SongSearchResult(
            track_id=t["track_id"],
            name=t["name"],
            artist=t["artist"],
            image=t["image"],
        )
        for t in merged
    ]


"""
    Refresh broken / missing album-cover URLs for songs already in the DB.
    Last.fm's placeholder hash (and any null image) gets replaced with a fresh
    URL from the cover service.
"""
@router.post("/backfill-covers")
def backfill_covers(limit: int = Query(default=200, ge=1, le=2000)):
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT track_id, name, artist FROM songs
            WHERE image IS NULL
               OR image LIKE %s
            LIMIT %s
        """, (f"%{ '2a96cbd8b46e442fc41c2b86b821562f' }%", limit))
        rows = cursor.fetchall()

    if not rows:
        return {"checked": 0, "updated": 0}

    with ThreadPoolExecutor(max_workers=8) as pool:
        covers = list(pool.map(lambda r: get_cover_url(r["artist"], r["name"]), rows))

    updated = 0
    with get_cursor() as cursor:
        for row, cover in zip(rows, covers):
            if cover:
                cursor.execute(
                    "UPDATE songs SET image = %s WHERE track_id = %s",
                    (cover, row["track_id"]),
                )
                updated += 1
    return {"checked": len(rows), "updated": updated}


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
