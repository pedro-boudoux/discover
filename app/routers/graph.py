from fastapi import APIRouter, HTTPException
from app.models import GraphResponse, GraphNode, GraphEdge, SeedRequest
from app.db import get_cursor
from app.services import lastfm, embeddings
from app.config import MAX_LISTENERS, DEFAULT_K

SIMILAR_TRACK_LISTENER_CAPS = [MAX_LISTENERS, 1_000_000, 2_000_000, 10_000_000]
SEED_SIMILAR_LIMIT = 25
EXPANSION_DEPTH = 3
EXPANSION_LIMIT = 10

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("", response_model=GraphResponse)
def get_graph():
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT s.track_id, s.name, s.artist, s.listeners, gn.is_seed
            FROM graph_nodes gn
            JOIN songs s ON gn.track_id = s.track_id
        """)
        nodes = [
            GraphNode(
                track_id=row["track_id"],
                name=row["name"],
                artist=row["artist"],
                is_seed=row["is_seed"],
                listeners=row["listeners"]
            )
            for row in cursor.fetchall()
        ]

        cursor.execute("SELECT source_id, target_id, similarity FROM graph_edges")
        edges = [
            GraphEdge(
                source=row["source_id"],
                target=row["target_id"],
                similarity=row["similarity"]
            )
            for row in cursor.fetchall()
        ]

    return GraphResponse(nodes=nodes, edges=edges)


@router.post("/seed")
def add_seed(request: SeedRequest):
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT name, artist, listeners, embedding FROM songs WHERE track_id = %s",
            (request.track_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Track not found — search for it first")

    name, artist = row["name"], row["artist"]

    if row["embedding"] is not None:
        # already cached — skip all API calls
        vector = [float(x) for x in row["embedding"]]
    else:
        # first time seeing this song — fetch everything and store it
        lastfm_track = lastfm.get_track_info(artist, name)

        artist_tags = lastfm.get_artist_top_tags(artist)
        track_tags = lastfm.get_track_top_tags(artist, name)
        similar_artists = lastfm.get_similar_artists(artist)
        similar_tags = [(lastfm.get_artist_top_tags(a["artist"]), a["match"]) for a in similar_artists]
        tag_counts = lastfm.blend_tags(artist_tags, track_tags, similar_tags)
        embeddings.get_or_create_tag_ids(list(tag_counts.keys()))
        vector = embeddings.build_tag_vector(tag_counts)

        with get_cursor() as cursor:
            cursor.execute("""
                UPDATE songs SET listeners = %s, embedding = %s WHERE track_id = %s
            """, (lastfm_track["listeners"], vector, request.track_id))

    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO graph_nodes (track_id, is_seed)
            VALUES (%s, true)
            ON CONFLICT (track_id) DO UPDATE SET is_seed = true
        """, (request.track_id,))

    with get_cursor() as cursor:
        cursor.execute("""
            SELECT track_id, name, artist, listeners, image,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM songs
            WHERE embedding IS NOT NULL
            AND listeners < %s
            AND track_id != %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (vector, MAX_LISTENERS, request.track_id, vector, DEFAULT_K))
        candidates = [dict(r) for r in cursor.fetchall()]

    similar = lastfm.get_similar_tracks(artist, name, limit=SEED_SIMILAR_LIMIT)
    seen_ids = {c["track_id"] for c in candidates} | {request.track_id}

    def process_similar_tracks(similar_list, listener_cap):
        added = 0
        for sim in similar_list:
            try:
                sim_id = embeddings.make_track_id(sim["artist"], sim["name"])
                if sim_id in seen_ids:
                    continue

                with get_cursor() as cursor:
                    cursor.execute(
                        "SELECT listeners, embedding FROM songs WHERE track_id = %s",
                        (sim_id,)
                    )
                    sim_row = cursor.fetchone()

                if sim_row and sim_row["embedding"] is not None:
                    if sim_row["listeners"] is not None and sim_row["listeners"] >= listener_cap:
                        continue
                    sim_vector = [float(x) for x in sim_row["embedding"]]
                else:
                    sim_lastfm = lastfm.get_track_info(sim["artist"], sim["name"])
                    if sim_lastfm["listeners"] >= listener_cap:
                        continue

                    sim_artist_tags = lastfm.get_artist_top_tags(sim["artist"])
                    sim_track_tags = lastfm.get_track_top_tags(sim["artist"], sim["name"])
                    sim_similar_artists = lastfm.get_similar_artists(sim["artist"])
                    sim_similar_tags = [(lastfm.get_artist_top_tags(a["artist"]), a["match"]) for a in sim_similar_artists]
                    sim_tag_counts = lastfm.blend_tags(sim_artist_tags, sim_track_tags, sim_similar_tags)
                    embeddings.get_or_create_tag_ids(list(sim_tag_counts.keys()))
                    sim_vector = embeddings.build_tag_vector(sim_tag_counts)

                    with get_cursor() as cursor:
                        cursor.execute("""
                            INSERT INTO songs (track_id, name, artist, listeners, embedding)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (track_id) DO UPDATE SET
                                listeners = EXCLUDED.listeners,
                                embedding = EXCLUDED.embedding
                        """, (sim_id, sim["name"], sim["artist"], sim_lastfm["listeners"], sim_vector))

                similarity = embeddings.cosine_similarity(vector, sim_vector)
                candidates.append({"track_id": sim_id, "similarity": similarity})
                seen_ids.add(sim_id)
                added += 1
            except Exception:
                continue
        return added

    # try escalating listener caps until we get at least one genre-relevant candidate
    for cap in SIMILAR_TRACK_LISTENER_CAPS:
        added = process_similar_tracks(similar, cap)
        if added > 0:
            break

    # recursive expansion: pull getSimilar from top candidates so the genre-correct pool
    # is thick enough that BFS playlists don't drift into unrelated music when they
    # exhaust the seed's direct edges
    expansion_seeds = sorted(candidates, key=lambda c: c["similarity"], reverse=True)[:EXPANSION_DEPTH]
    for cand in expansion_seeds:
        try:
            with get_cursor() as cursor:
                cursor.execute(
                    "SELECT name, artist FROM songs WHERE track_id = %s",
                    (cand["track_id"],)
                )
                cand_row = cursor.fetchone()
            if not cand_row:
                continue

            cand_similar = lastfm.get_similar_tracks(cand_row["artist"], cand_row["name"], limit=EXPANSION_LIMIT)
            for cap in SIMILAR_TRACK_LISTENER_CAPS:
                added = process_similar_tracks(cand_similar, cap)
                if added > 0:
                    break
        except Exception:
            continue

    # merge ANN + getSimilar + expansion results, keep top DEFAULT_K by similarity
    candidates = sorted(candidates, key=lambda c: c["similarity"], reverse=True)[:DEFAULT_K]

    if candidates:
        with get_cursor() as cursor:
            for c in candidates:
                cursor.execute("""
                    INSERT INTO graph_edges (source_id, target_id, similarity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_id, target_id) DO UPDATE SET similarity = EXCLUDED.similarity
                """, (request.track_id, c["track_id"], c["similarity"]))

    return {"track_id": request.track_id, "name": name, "artist": artist}
