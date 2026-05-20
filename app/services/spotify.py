import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from app.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

_auth = SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
)
sp = spotipy.Spotify(auth_manager=_auth)


"""
    Takes a free-text query (song name, artist, anything) and hits the spotify search API. Returns a list of tracks with spotify_id, name, artist, and album art URL.

    The user types something and this is what it finds.
"""
def search_songs(q: str, limit: int = 10):
    results = sp.search(q=q, type="track", limit=limit)
    tracks = []
    for item in results["tracks"]["items"]:
        tracks.append({
            "spotify_id": item["id"],
            "name": item["name"],
            "artist": item["artists"][0]["name"],
            "image": item["album"]["images"][0]["url"] if item["album"]["images"] else None
        })
    return tracks


"""
    Fetches a single track by its spotify ID and returns the same shape as search results. Used when you already have an ID and need to refresh or display its metadata
"""
def get_track(spotify_id: str):
    track = sp.track(spotify_id)
    return {
        "spotify_id": track["id"],
        "name": track["name"],
        "artist": track["artists"][0]["name"],
        "image": track["album"]["images"][0]["url"] if track["album"]["images"] else None
    }