from app.db import get_cursor
from app.services import lastfm, embeddings
from app.services.covers import get_cover_url


def embed_and_store_track(artist: str, name: str) -> dict | None:
    """
    Ensure a track is embedded and stored in the songs table, fetching tags from
    Last.fm when we haven't seen it before. Returns the full song row
    (track_id, name, artist, listeners, image, embedding) or None if the track
    can't be fetched.

    This is the shared building block behind seed bootstrapping and the
    recommendation top-up: both need to turn a (artist, name) pair into a stored
    embedding without duplicating the Last.fm/embedding pipeline.
    """
    track_id = embeddings.make_track_id(artist, name)
    canonical_key = embeddings.make_canonical_key(artist, name)

    with get_cursor() as cursor:
        cursor.execute(
            "SELECT track_id, name, artist, listeners, image, embedding FROM songs WHERE track_id = %s",
            (track_id,),
        )
        row = cursor.fetchone()

    if row and row["embedding"] is not None:
        return {
            "track_id": track_id,
            "name": row["name"],
            "artist": row["artist"],
            "listeners": row["listeners"],
            "image": row["image"],
            "embedding": [float(x) for x in row["embedding"]],
        }

    info = lastfm.get_track_info(artist, name)

    artist_tags = lastfm.get_artist_top_tags(artist)
    track_tags = lastfm.get_track_top_tags(artist, name)
    similar_artists = lastfm.get_similar_artists(artist)
    similar_tags = [(lastfm.get_artist_top_tags(a["artist"]), a["match"]) for a in similar_artists]
    tag_counts = lastfm.blend_tags(artist_tags, track_tags, similar_tags)
    embeddings.get_or_create_tag_ids(list(tag_counts.keys()))
    vector = embeddings.build_tag_vector(tag_counts)
    image = get_cover_url(artist, name)

    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO songs (track_id, name, artist, listeners, embedding, image, canonical_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (track_id) DO UPDATE SET
                listeners = EXCLUDED.listeners,
                embedding = EXCLUDED.embedding,
                image = COALESCE(EXCLUDED.image, songs.image),
                canonical_key = EXCLUDED.canonical_key
        """, (track_id, name, artist, info["listeners"], vector, image, canonical_key))

    return {
        "track_id": track_id,
        "name": name,
        "artist": artist,
        "listeners": info["listeners"],
        "image": image,
        "embedding": vector,
    }
