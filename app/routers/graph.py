from fastapi import APIRouter, HTTPException
from app.models import GraphResponse, GraphNode, GraphEdge, SeedRequest
from app.db import get_cursor
from app.services import lastfm, embeddings
from app.config import MAX_LISTENERS, DEFAULT_K

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
            "SELECT name, artist FROM songs WHERE track_id = %s",
            (request.track_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Track not found — search for it first")

    name, artist = row["name"], row["artist"]

    lastfm_track = lastfm.get_track_info(artist, name)
    if lastfm_track["listeners"] >= MAX_LISTENERS:
        raise HTTPException(
            400,
            f"Song has {lastfm_track['listeners']} listeners, exceeds underground threshold of {MAX_LISTENERS}"
        )

    artist_tags = lastfm.get_artist_top_tags(artist)
    tag_counts = {**{t: 50 for t in lastfm_track["tags"][:5]}, **artist_tags}
    embeddings.get_or_create_tag_ids(list(tag_counts.keys()))
    vector = embeddings.build_tag_vector(tag_counts)

    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE songs SET listeners = %s, embedding = %s WHERE track_id = %s
        """, (lastfm_track["listeners"], vector, request.track_id))

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

    if len(candidates) < DEFAULT_K:
        similar = lastfm.get_similar_tracks(artist, name, limit=DEFAULT_K)
        seen_ids = {c["track_id"] for c in candidates} | {request.track_id}

        for sim in similar:
            if len(candidates) >= DEFAULT_K:
                break
            try:
                sim_id = embeddings.make_track_id(sim["artist"], sim["name"])
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
                        INSERT INTO songs (track_id, name, artist, listeners, embedding)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (track_id) DO UPDATE SET
                            listeners = EXCLUDED.listeners,
                            embedding = EXCLUDED.embedding
                    """, (sim_id, sim["name"], sim["artist"], sim_lastfm["listeners"], sim_vector))

                similarity = embeddings.cosine_similarity(vector, sim_vector)
                candidates.append({"track_id": sim_id, "similarity": similarity})
                seen_ids.add(sim_id)
            except Exception:
                continue

    if candidates:
        with get_cursor() as cursor:
            for c in candidates:
                cursor.execute("""
                    INSERT INTO graph_edges (source_id, target_id, similarity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_id, target_id) DO UPDATE SET similarity = EXCLUDED.similarity
                """, (request.track_id, c["track_id"], c["similarity"]))

    return {"track_id": request.track_id, "name": name, "artist": artist}
