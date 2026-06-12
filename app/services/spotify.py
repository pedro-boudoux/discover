import time
import threading

import requests

from app.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"

# Cached client-credentials token. Spotify tokens last ~1h; we refresh a little
# early. Guarded by a lock because FastAPI serves requests across threads.
_token: str | None = None
_token_expires_at: float = 0.0
_lock = threading.Lock()


class SpotifyUnavailable(Exception):
    """Spotify couldn't be reached or isn't configured — the result is *unknown*,
    as opposed to a successful search that found no match. Callers should not
    persist this outcome so the lookup is retried later."""


def _get_token() -> str:
    """Fetch (and cache) an app-only access token via the client-credentials flow.

    Raises SpotifyUnavailable when Spotify isn't configured or the token request
    fails — neither is a definitive "song not found" answer.
    """
    global _token, _token_expires_at

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        raise SpotifyUnavailable("Spotify credentials are not configured")

    with _lock:
        if _token and time.time() < _token_expires_at:
            return _token

        try:
            resp = requests.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SpotifyUnavailable("Spotify token request failed") from exc

        _token = data.get("access_token")
        if not _token:
            raise SpotifyUnavailable("Spotify token response had no access_token")
        # Refresh 60s before the real expiry to avoid races near the boundary.
        _token_expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
        return _token


def find_track_url(artist: str, name: str) -> str | None:
    """Resolve the public open.spotify.com URL for a track.

    Returns the URL, or None when the search genuinely found no match (a
    definitive answer worth caching). Raises SpotifyUnavailable on any
    auth/network/parse failure so the caller can avoid caching a non-answer.
    """
    token = _get_token()

    query = f'track:"{name}" artist:"{artist}"'
    try:
        resp = requests.get(
            SEARCH_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "track", "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("tracks", {}).get("items", [])
    except (requests.RequestException, ValueError) as exc:
        raise SpotifyUnavailable("Spotify search request failed") from exc

    if not items:
        return None
    return items[0].get("external_urls", {}).get("spotify")