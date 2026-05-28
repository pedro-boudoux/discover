import requests
from urllib.parse import quote

DEEZER_URL = "https://api.deezer.com/search"
DEEZER_ARTIST_URL = "https://api.deezer.com/search/artist"
ITUNES_URL = "https://itunes.apple.com/search"

# Last.fm's "no image" placeholder hash — anything matching this is a stale
# Last.fm CDN URL that doesn't actually point at an album cover.
LASTFM_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"


def is_broken_image(url: str | None) -> bool:
    if not url:
        return True
    return LASTFM_PLACEHOLDER_HASH in url


def _deezer_cover(artist: str, name: str) -> str | None:
    try:
        q = f'artist:"{artist}" track:"{name}"'
        resp = requests.get(DEEZER_URL, params={"q": q, "limit": 1}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        for r in data.get("data", []):
            cover = r.get("album", {}).get("cover_xl")
            if cover:
                return cover
    except (requests.RequestException, ValueError):
        return None
    return None


def _itunes_cover(artist: str, name: str) -> str | None:
    try:
        term = quote(f"{artist} {name}")
        resp = requests.get(
            ITUNES_URL,
            params={"term": term, "entity": "song", "limit": 5},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        artist_lower = artist.lower()
        name_lower = name.lower()
        for r in data.get("results", []):
            if (
                artist_lower in r.get("artistName", "").lower()
                and name_lower in r.get("trackName", "").lower()
            ):
                url = r.get("artworkUrl100")
                if url:
                    return url.replace("100x100bb.jpg", "600x600bb.jpg")
        if data.get("results"):
            url = data["results"][0].get("artworkUrl100")
            if url:
                return url.replace("100x100bb.jpg", "600x600bb.jpg")
    except (requests.RequestException, ValueError):
        return None
    return None


def _deezer_artist_image(artist: str) -> str | None:
    try:
        resp = requests.get(
            DEEZER_ARTIST_URL,
            params={"q": artist, "limit": 1},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        for r in data.get("data", []):
            pic = r.get("picture_xl")
            if pic and "dzcdn.net" in pic:
                return pic
    except (requests.RequestException, ValueError):
        return None
    return None


def get_cover_url(artist: str, name: str) -> str | None:
    """
    Try Deezer album cover first (best for underground), then iTunes album cover,
    then fall back to a Deezer artist photo. Last.fm artist images are not used
    because Last.fm removed them years ago and serves the same broken placeholder
    for every artist.
    """
    return (
        _deezer_cover(artist, name)
        or _itunes_cover(artist, name)
        or _deezer_artist_image(artist)
    )
