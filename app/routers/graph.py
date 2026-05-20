from fastapi import APIRouter, HTTPException
from app.models import GraphResponse, GraphNode, GraphEdge, SeedRequest
from app.db import get_cursor
from app.services import spotify, lastfm, embeddings
from app.config import MAX_LISTENERS, DEFAULT_K

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("", response_model=GraphResponse)
def get_graph():
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT s.spotify_id, s.name, s.artist, s.listeners, gn.is_seed
            FROM graph_nodes gn
            JOIN songs s ON gn.spotify_id = s.spotify_id
        """)
        nodes = [
            GraphNode(
                spotify_id=row["spotify_id"],
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
    track = spotify.get_track(request.spotify_id)
    lastfm_track = lastfm.get_track_info(track["artist"], track["name"])

    if lastfm_track["listeners"] >= MAX_LISTENERS:
        raise HTTPException(
            400,
            f"Song has {lastfm_track['listeners']} listeners, exceeds underground threshold of {MAX_LISTENERS}"
        )

    artist_tags = lastfm.get_artist_top_tags(track["artist"])
    tag_counts = {**{t: 50 for t in lastfm_track["tags"][:5]}, **artist_tags}
    embeddings.get_or_create_tag_ids(list(tag_counts.keys()))
    vector = embeddings.build_tag_vector(tag_counts)

    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO songs (spotify_id, name, artist, listeners, image, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (spotify_id) DO UPDATE SET
                listeners = EXCLUDED.listeners,
                image = EXCLUDED.image,
                embedding = EXCLUDED.embedding
        """, (request.spotify_id, track["name"], track["artist"],
              lastfm_track["listeners"], track["image"], vector))

        cursor.execute("""
            INSERT INTO graph_nodes (spotify_id, is_seed)
            VALUES (%s, true)
            ON CONFLICT (spotify_id) DO UPDATE SET is_seed = true
        """, (request.spotify_id,))

    # ANN search for existing candidates
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT spotify_id, name, artist, listeners, image,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM songs
            WHERE embedding IS NOT NULL
            AND listeners < %s
            AND spotify_id != %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (vector, MAX_LISTENERS, request.spotify_id, vector, DEFAULT_K))
        candidates = [dict(r) for r in cursor.fetchall()]

    # Cold-start: supplement from Last.fm similar tracks when DB is sparse
    if len(candidates) < DEFAULT_K:
        similar = lastfm.get_similar_tracks(track["artist"], track["name"], limit=DEFAULT_K)
        seen_ids = {c["spotify_id"] for c in candidates} | {request.spotify_id}

        for sim in similar:
            if len(candidates) >= DEFAULT_K:
                break
            try:
                results = spotify.search_songs(f"{sim['name']} {sim['artist']}", limit=1)
                if not results:
                    continue
                sim_id = results[0]["spotify_id"]
                if sim_id in seen_ids:
                    continue

                sim_lastfm = lastfm.get_track_info(sim["artist"], sim["name"])
                if sim_lastfm["listeners"] >= MAX_LISTENERS:
                    continue

                sim_artist_tags = lastfm.get_artist_top_tags(sim["artist"])
                sim_tag_counts = {**{t: 50 for t in sim_lastfm["tags"][:5]}, **sim_artist_tags}
                embeddings.get_or_create_tag_ids(list(sim_tag_counts.keys()))
                sim_vector = embeddings.build_tag_vector(sim_tag_counts)

                with get_cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO songs (spotify_id, name, artist, listeners, image, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (spotify_id) DO UPDATE SET
                            listeners = EXCLUDED.listeners,
                            image = EXCLUDED.image,
                            embedding = EXCLUDED.embedding
                    """, (sim_id, results[0]["name"], results[0]["artist"],
                          sim_lastfm["listeners"], results[0]["image"], sim_vector))

                similarity = embeddings.cosine_similarity(vector, sim_vector)
                candidates.append({
                    "spotify_id": sim_id,
                    "similarity": similarity
                })
                seen_ids.add(sim_id)
            except Exception:
                continue

    # Write edges for all candidates
    if candidates:
        with get_cursor() as cursor:
            for c in candidates:
                cursor.execute("""
                    INSERT INTO graph_edges (source_id, target_id, similarity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_id, target_id) DO UPDATE SET similarity = EXCLUDED.similarity
                """, (request.spotify_id, c["spotify_id"], c["similarity"]))

    return {"spotify_id": request.spotify_id, "name": track["name"], "artist": track["artist"]}
