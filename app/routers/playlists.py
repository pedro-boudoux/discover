from fastapi import APIRouter, HTTPException
from app.models import LinearPlaylistRequest, TreePlaylistRequest, PlaylistResponse, PlaylistTrack
from app.db import get_cursor
from app.services import ingest, embeddings as emb_service
from app.config import MAX_LISTENERS

router = APIRouter(prefix="/playlists", tags=["playlists"])

NICHE_THRESHOLDS = [100, 1_000, 10_000, 100_000, MAX_LISTENERS]


def embed_missing(track_ids: set):
    if not track_ids:
        return
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT artist, name FROM songs WHERE track_id = ANY(%s) AND embedding IS NULL",
            (list(track_ids),)
        )
        unembedded = cursor.fetchall()

    # Neighborhood tracks are already in the graph, so an unbounded cap keeps the
    # shared pipeline from skipping any of them for being too popular.
    for row in unembedded:
        try:
            ingest.embed_and_store_track(row["artist"], row["name"])
        except Exception:
            pass


def get_neighborhood(cursor, track_id: str) -> set:
    cursor.execute(
        "SELECT target_id FROM graph_edges WHERE source_id = %s",
        (track_id,)
    )
    return {row["target_id"] for row in cursor.fetchall()}


def find_neighbors(cursor, embedding, exclude_ids, k, niche, allowed_ids=None):
    if not niche:
        return emb_service.ann_search(
            embedding, exclude_ids=exclude_ids,
            allowed_ids=allowed_ids, limit=k, cursor=cursor,
        )

    collected = []
    excluded = set(exclude_ids)

    for threshold in NICHE_THRESHOLDS:
        if len(collected) >= k:
            break
        results = emb_service.ann_search(
            embedding, listeners_cap=threshold, exclude_ids=excluded,
            allowed_ids=allowed_ids, limit=k - len(collected), cursor=cursor,
        )
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

    embed_missing(neighborhood)

    with get_cursor() as cursor:
        tracks = find_neighbors(
            cursor, seed_embedding,
            {request.track_id, *request.exclude_ids},
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
        allowed = get_neighborhood(cursor, request.track_id)

    embed_missing(allowed)

    with get_cursor() as cursor:
        # allowed set starts as the seed's direct neighbors and grows as we visit nodes

        playlist = []
        seen = {request.track_id, *request.exclude_ids}
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
