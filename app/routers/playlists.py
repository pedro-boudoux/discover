from fastapi import APIRouter, HTTPException
from app.models import LinearPlaylistRequest, TreePlaylistRequest, PlaylistResponse, PlaylistTrack
from app.db import get_cursor
from app.config import MAX_LISTENERS

router = APIRouter(prefix="/playlists", tags=["playlists"])

NICHE_THRESHOLDS = [100, 1_000, 10_000, 100_000, MAX_LISTENERS]


def get_neighborhood(cursor, track_id: str) -> set:
    cursor.execute(
        "SELECT target_id FROM graph_edges WHERE source_id = %s",
        (track_id,)
    )
    return {row["target_id"] for row in cursor.fetchall()}


def fetch_neighbors(cursor, embedding, exclude_ids, listeners_cap, k, allowed_ids=None):
    if allowed_ids:
        cursor.execute("""
            SELECT track_id, name, artist, listeners, image, embedding,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM songs
            WHERE embedding IS NOT NULL
            AND listeners < %s
            AND track_id != ALL(%s)
            AND track_id = ANY(%s)
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (embedding, listeners_cap, list(exclude_ids), list(allowed_ids), embedding, k))
    else:
        cursor.execute("""
            SELECT track_id, name, artist, listeners, image, embedding,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM songs
            WHERE embedding IS NOT NULL
            AND listeners < %s
            AND track_id != ALL(%s)
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (embedding, listeners_cap, list(exclude_ids), embedding, k))
    return [dict(r) for r in cursor.fetchall()]


def find_neighbors(cursor, embedding, exclude_ids, k, niche, allowed_ids=None):
    if not niche:
        return fetch_neighbors(cursor, embedding, exclude_ids, MAX_LISTENERS, k, allowed_ids)

    collected = []
    excluded = set(exclude_ids)

    for threshold in NICHE_THRESHOLDS:
        if len(collected) >= k:
            break
        results = fetch_neighbors(cursor, embedding, excluded, threshold, k - len(collected), allowed_ids)
        for r in results:
            collected.append(r)
            excluded.add(r["track_id"])

    return sorted(collected, key=lambda x: x["listeners"] or 0)


def to_playlist_track(row: dict) -> PlaylistTrack:
    return PlaylistTrack(
        track_id=row["track_id"],
        name=row["name"],
        artist=row["artist"],
        similarity=round(row["similarity"], 3),
        listeners=row["listeners"] or 0,
        image=row.get("image")
    )


@router.post("/linear", response_model=PlaylistResponse)
def linear_playlist(request: LinearPlaylistRequest):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT embedding FROM songs WHERE track_id = %s",
            (request.track_id,)
        )
        row = cursor.fetchone()
        if not row or row["embedding"] is None:
            raise HTTPException(404, "Track not found or not yet embedded — seed it first")

        seed_embedding = [float(x) for x in row["embedding"]]
        neighborhood = get_neighborhood(cursor, request.track_id)
        tracks = find_neighbors(
            cursor, seed_embedding, {request.track_id},
            request.n, request.niche,
            neighborhood if neighborhood else None
        )

    return PlaylistResponse(
        seed_track_id=request.track_id,
        tracks=[to_playlist_track(t) for t in tracks]
    )


@router.post("/tree", response_model=PlaylistResponse)
def tree_playlist(request: TreePlaylistRequest):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT embedding FROM songs WHERE track_id = %s",
            (request.track_id,)
        )
        row = cursor.fetchone()
        if not row or row["embedding"] is None:
            raise HTTPException(404, "Track not found or not yet embedded — seed it first")

        seed_embedding = [float(x) for x in row["embedding"]]

        # allowed set starts as the seed's direct neighbors and grows as we visit nodes
        allowed = get_neighborhood(cursor, request.track_id)

        playlist = []
        seen = {request.track_id}
        queue = [(request.track_id, seed_embedding, 0)]

        while queue and len(playlist) < request.n:
            track_id, embedding, depth = queue.pop(0)
            if depth >= request.max_depth:
                continue

            # expand allowed set with this node's own edges if it has any
            allowed.update(get_neighborhood(cursor, track_id))
            current_allowed = allowed - seen

            neighbors = find_neighbors(
                cursor, embedding, seen, 2, request.niche,
                current_allowed if current_allowed else None
            )

            for neighbor in neighbors:
                if len(playlist) >= request.n:
                    break
                playlist.append(neighbor)
                seen.add(neighbor["track_id"])
                queue.append((neighbor["track_id"], [float(x) for x in neighbor["embedding"]], depth + 1))

    return PlaylistResponse(
        seed_track_id=request.track_id,
        tracks=[to_playlist_track(t) for t in playlist]
    )
