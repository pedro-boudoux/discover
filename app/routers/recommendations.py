from fastapi import APIRouter, Query, HTTPException
from app.models import RecommendationsResponse, Recommendation
from app.db import get_cursor
from app.services import steering, lastfm, ingest, embeddings
from app.services.embeddings import mmr_rerank
from app.config import MAX_LISTENERS, DEFAULT_K, MMR_LAMBDA, MMR_POOL_MULTIPLIER, MMR_MAX_PER_ARTIST

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# How many of the seed's Last.fm similar tracks to try when the local pool
# can't satisfy the requested k (the exhaustion top-up).
TOPUP_SIMILAR_LIMIT = 30


def topup_from_lastfm(seed_track_id: str, query_embedding: list, exclude_ids: set[str], needed: int) -> list[dict]:
    """
    Fall back to Last.fm when the local DB doesn't hold enough unseen underground
    neighbors to fill k. Pulls the seed's similar tracks, embeds+stores any we
    haven't seen, and returns up to `needed` of them scored against the query
    embedding. Each Last.fm track is a few API calls, so this only runs when the
    vector search genuinely came up short.
    """
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT name, artist FROM songs WHERE track_id = %s",
            (seed_track_id,),
        )
        seed = cursor.fetchone()
    if not seed:
        return []

    similar = lastfm.get_similar_tracks(seed["artist"], seed["name"], limit=TOPUP_SIMILAR_LIMIT)

    added: list[dict] = []
    excluded = set(exclude_ids)
    for sim in similar:
        if len(added) >= needed:
            break
        try:
            sim_id = embeddings.make_track_id(sim["artist"], sim["name"])
            if sim_id in excluded:
                continue
            song = ingest.embed_and_store_track(sim["artist"], sim["name"], MAX_LISTENERS)
            if song is None:
                continue
            added.append({
                "track_id": song["track_id"],
                "name": song["name"],
                "artist": song["artist"],
                "listeners": song["listeners"] or 0,
                "image": song["image"],
                "similarity": round(embeddings.cosine_similarity(query_embedding, song["embedding"]), 3),
            })
            excluded.add(sim_id)
        except Exception:
            continue

    return added


@router.get("/{track_id}", response_model=RecommendationsResponse)
def get_recommendations(
    track_id: str,
    k: int = Query(default=DEFAULT_K, ge=1, le=50),
    lambda_param: float = Query(default=MMR_LAMBDA, ge=0.0, le=1.0, alias="lambda"),
    exclude: list[str] = Query(default=[])
):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT name, artist, embedding FROM songs WHERE track_id = %s",
            (track_id,)
        )
        row = cursor.fetchone()

    # Unknown track — we have no name/artist to embed from, so this is a 404
    # rather than an empty result (mirrors /graph/seed and /songs/{id}/features).
    if not row:
        raise HTTPException(404, "Track not found — search for it first")

    if row["embedding"] is None:
        # Cold seed: embed it on demand instead of bailing. Pass an effectively
        # unbounded listener cap so the seed itself is never filtered out for
        # being too popular — the underground cap only applies to candidates.
        song = ingest.embed_and_store_track(row["artist"], row["name"], listener_cap=float("inf"))
        base_embedding = song["embedding"] if song else None
    else:
        base_embedding = list(row["embedding"])

    # No tags anywhere (or every tag fell outside the vocab window) yields an
    # all-zero vector, which makes cosine distance meaningless. There's genuinely
    # nothing to recommend, so return empty rather than NaN-ranked garbage.
    if not base_embedding or not any(base_embedding):
        return RecommendationsResponse(recommendations=[])

    steered_embedding = steering.apply_steering(base_embedding, track_id)
    exclude_ids = list({track_id, *exclude})

    pool = embeddings.ann_search(
        steered_embedding,
        listeners_cap=MAX_LISTENERS,
        exclude_ids=exclude_ids,
        limit=k * MMR_POOL_MULTIPLIER,
    )

    artist_counts: dict[str, int] = {}
    capped_pool = []
    overflow = []  # candidates dropped only because of the per-artist cap
    for candidate in pool:
        artist = str(candidate["artist"])
        if artist_counts.get(artist, 0) < MMR_MAX_PER_ARTIST:
            capped_pool.append(candidate)
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
        else:
            overflow.append(candidate)

    reranked = mmr_rerank(steered_embedding, capped_pool, k, lambda_param)

    # The per-artist cap keeps recommendations diverse, but when a seed's
    # neighborhood is dominated by a few artists it can leave us short of k.
    # Backfill from the capped-out candidates (most similar first) so the
    # requested count is honored whenever the pool physically has enough songs.
    if len(reranked) < k and overflow:
        overflow.sort(key=lambda c: c["similarity"], reverse=True)
        reranked.extend(overflow[: k - len(reranked)])

    # Still short after exhausting the local DB — the neighborhood is sparse or
    # mostly already explored. Top up with fresh candidates from Last.fm.
    if len(reranked) < k:
        already = {r["track_id"] for r in reranked} | set(exclude_ids)
        reranked.extend(
            topup_from_lastfm(track_id, steered_embedding, already, k - len(reranked))
        )

    recommendations = [
        Recommendation(
            track_id=r["track_id"],
            name=r["name"],
            artist=r["artist"],
            similarity=r["similarity"],
            listeners=r["listeners"],
            image=r["image"],
        )
        for r in reranked
    ]

    return RecommendationsResponse(recommendations=recommendations)
