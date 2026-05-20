import requests
from app.config import LASTFM_API_KEY

BASE_URL = "http://ws.audioscrobbler.com/2.0"


def _request(method: str, **params):
    params["method"] = method
    params["api_key"] = LASTFM_API_KEY
    params["format"] = "json"
    resp = requests.get(BASE_URL, params=params)
    resp.raise_for_status()
    return resp.json()


"""
    fetches listener count, playcount and a basic tag list for a specific track, the listener count is our underground filter. we want less than 500k listens to keep it niche or whatever
"""
def get_track_info(artist: str, track: str) -> dict:
    data = _request("track.getInfo", artist=artist, track=track)
    track_data = data.get("track", {})

    listeners = int(track_data.get("listeners", 0))
    playcount = int(track_data.get("playcount", 0))

    toptags = track_data.get("toptags", {}).get("tag", [])
    tags = [t["name"].lower().strip() for t in toptags]

    return {
        "listeners": listeners,
        "playcount": playcount,
        "tags": tags
    }


"""
    core of the embedding pipeline, returns a tag_name : count dict where count is how many users applied that tag to the artist (our confidence score) this dict is what gets passed into embeddings.py to become a vector

"""
def get_artist_top_tags(artist: str) -> dict:
    data = _request("artist.getTopTags", artist=artist)
    toptags = data.get("toptags", {}).get("tag", [])

    tag_counts = {}
    for t in toptags:
        name = t["name"].lower().strip()
        count = int(t["count"])
        tag_counts[name] = count

    return tag_counts


"""
    asks last.fm for tracks similar to a given one, ideally we want to use our vectordb but at the start we'll probably be using this a lot since our db will be quite sparse
"""
def search_tracks(query: str, limit: int = 10) -> list:
    data = _request("track.search", track=query, limit=limit)
    tracks = data.get("results", {}).get("trackmatches", {}).get("track", [])

    results = []
    for t in tracks:
        images = t.get("image", [])
        image = next((img["#text"] for img in reversed(images) if img.get("#text")), None)
        results.append({
            "name": t["name"],
            "artist": t["artist"],
            "listeners": int(t.get("listeners", 0)),
            "image": image
        })
    return results


def get_similar_tracks(artist: str, track: str, limit: int = 10) -> list:
    data = _request("track.getSimilar", artist=artist, track=track, limit=limit)
    similar = data.get("similartracks", {}).get("track", [])

    results = []
    for t in similar:
        results.append({
            "name": t["name"],
            "artist": t["artist"]["name"],
            "match": float(t.get("match", 0))
        })

    return results