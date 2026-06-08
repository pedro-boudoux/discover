from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Query, HTTPException
from app.models import SongSearchResult, TrackFeatures
from app.services import lastfm, ingest, embeddings as emb_service
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

    # Local DB lookup + Last.fm search run concurrently.
    # Last.fm failures (5xx, timeout, network) degrade gracefully to local-only.
    with ThreadPoolExecutor(max_workers=2) as pool:
        local_future = pool.submit(_search_local_songs, q)
        lastfm_future = pool.submit(lastfm.search_tracks, q)
        local_tracks = local_future.result()
        try:
            lastfm_tracks = lastfm_future.result()
        except Exception:
            lastfm_tracks = []

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
    Re-pack tag_vocab ids to be dense (1..N) and null all stale embeddings so
    they get rebuilt on the next /reembed call. Idempotent: skips the repack
    when max(id) == count(*) (ids are already dense). Run once after any DB
    that was written by the old INSERT…ON CONFLICT DO UPDATE code that burned
    SERIAL ids on conflicts, causing ids to race past EMBEDDING_DIM and silently
    drop tags from every embedding.
"""
@router.post("/repack-vocab")
def repack_vocab():
    with get_cursor() as cursor:
        cursor.execute("SELECT max(id) AS max_id, count(*) AS cnt FROM tag_vocab")
        row = cursor.fetchone()
    max_id = row["max_id"] or 0
    count  = row["cnt"]    or 0

    if max_id <= count:
        return {"repacked": False, "tags": count, "nulled_embeddings": 0}

    # Shift all ids up by 1_000_000 so new dense values (1..N) can't collide
    # with any current value during the second UPDATE.
    with get_cursor() as cursor:
        cursor.execute("UPDATE tag_vocab SET id = id + 1000000")

    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE tag_vocab tv
            SET id = r.new_id
            FROM (
                SELECT tag,
                       (dense_rank() OVER (ORDER BY id - 1000000))::int AS new_id
                FROM tag_vocab
            ) r
            WHERE r.tag = tv.tag
        """)
        cursor.execute(
            "SELECT setval('tag_vocab_id_seq', (SELECT max(id) FROM tag_vocab))"
        )

    # All existing embeddings were built against the old id→slot mapping; null
    # them so /reembed rebuilds every vector against the repacked vocab.
    with get_cursor() as cursor:
        cursor.execute("UPDATE songs SET embedding = NULL")
        cursor.execute("SELECT count(*) AS cnt FROM songs")
        nulled = cursor.fetchone()["cnt"]

    return {"repacked": True, "tags": count, "nulled_embeddings": nulled}


"""
    Re-embed up to `limit` songs whose embedding is NULL (e.g. after /repack-vocab).
    Each song re-fetches its tags from Last.fm and rebuilds the vector against the
    current tag_vocab. Call repeatedly with the same limit until `remaining` hits 0.
    Uses 2 parallel workers — Last.fm free tier allows ~5 req/s per key and each
    song makes ~7 sequential calls, so this stays comfortably within the limit.
"""
@router.post("/reembed")
def reembed_songs(limit: int = Query(default=50, ge=1, le=500)):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT track_id, name, artist FROM songs WHERE embedding IS NULL LIMIT %s",
            (limit,),
        )
        batch = cursor.fetchall()

    def _reembed(song):
        try:
            result = ingest.embed_and_store_track(song["artist"], song["name"])
            return result is not None
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(_reembed, batch))

    embedded = sum(1 for ok in outcomes if ok)
    failed   = sum(1 for ok in outcomes if not ok)

    with get_cursor() as cursor:
        cursor.execute("SELECT count(*) AS cnt FROM songs WHERE embedding IS NULL")
        remaining = cursor.fetchone()["cnt"]

    return {"embedded": embedded, "failed": failed, "remaining": remaining}


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
        cursor.execute(
            "SELECT name, artist, listeners, embedding FROM songs WHERE track_id = %s",
            (track_id,)
        )
        row = cursor.fetchone()

    if not row:
        raise HTTPException(404, "Track not found — search for it first")

    if row["embedding"] is not None:
        # cache hit — reuse the stored vector, no API calls
        name, artist = row["name"], row["artist"]
        listeners = row["listeners"] or 0
        embedding = [float(x) for x in row["embedding"]]
    else:
        # cache miss — run the shared embedding pipeline. An unbounded cap means
        # features works for any track regardless of popularity.
        song = ingest.embed_and_store_track(row["artist"], row["name"])
        if song is None:
            raise HTTPException(502, "Could not fetch track data from Last.fm")
        name, artist = song["name"], song["artist"]
        listeners = song["listeners"] or 0
        embedding = song["embedding"]

    # derive the track's tags from its embedding: any vocab tag whose slot is
    # non-zero. Same derivation for hot and cold paths, so they agree.
    with get_cursor() as cursor:
        cursor.execute("SELECT id, tag FROM tag_vocab WHERE id < %s", (EMBEDDING_DIM,))
        tags = [
            r["tag"] for r in cursor.fetchall()
            if r["id"] < len(embedding) and embedding[r["id"]] > 0
        ]

    return TrackFeatures(
        track_id=track_id,
        name=name,
        artist=artist,
        listeners=listeners,
        tags=tags,
        embedding=embedding
    )
