"""
Tier-1 unit tests for app/services/spotify.py.

Covers the client-credentials token flow and find_track_url, with a focus on the
key invariant the DB cache relies on: a *definitive* "no match" returns None,
while an unreachable/unconfigured Spotify raises SpotifyUnavailable (so callers
don't persist a non-answer).

All network I/O (requests.post / requests.get) is monkeypatched.
"""

import pytest
import requests

from app.services import spotify
from app.services.spotify import SpotifyUnavailable, find_track_url


class FakeResp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, json_data=None, raise_exc=None):
        self._json = json_data or {}
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise is not None:
            raise self._raise

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def reset_token_cache(monkeypatch):
    """Each test starts with an empty token cache and credentials configured.

    Individual tests can re-monkeypatch the creds to None to exercise the
    unconfigured path.
    """
    monkeypatch.setattr(spotify, "_token", None)
    monkeypatch.setattr(spotify, "_token_expires_at", 0.0)
    monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_ID", "client-id")
    monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_SECRET", "client-secret")


# ---------------------------------------------------------------------------
# _get_token
# ---------------------------------------------------------------------------

class TestGetToken:
    def test_unconfigured_raises(self, monkeypatch):
        monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_ID", None)
        monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_SECRET", None)
        with pytest.raises(SpotifyUnavailable):
            spotify._get_token()

    def test_partial_creds_raises(self, monkeypatch):
        """An id without a secret (or vice versa) is treated as unconfigured."""
        monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_SECRET", None)
        with pytest.raises(SpotifyUnavailable):
            spotify._get_token()

    def test_returns_and_caches_token(self, monkeypatch):
        calls = []

        def fake_post(url, **kw):
            calls.append(url)
            return FakeResp({"access_token": "tok-123", "expires_in": 3600})

        monkeypatch.setattr(spotify.requests, "post", fake_post)

        assert spotify._get_token() == "tok-123"
        # Second call should hit the cache, not re-request.
        assert spotify._get_token() == "tok-123"
        assert len(calls) == 1

    def test_token_request_http_error_raises(self, monkeypatch):
        def fake_post(url, **kw):
            return FakeResp(raise_exc=requests.RequestException("500"))

        monkeypatch.setattr(spotify.requests, "post", fake_post)
        with pytest.raises(SpotifyUnavailable):
            spotify._get_token()

    def test_missing_access_token_raises(self, monkeypatch):
        def fake_post(url, **kw):
            return FakeResp({"expires_in": 3600})  # no access_token

        monkeypatch.setattr(spotify.requests, "post", fake_post)
        with pytest.raises(SpotifyUnavailable):
            spotify._get_token()


# ---------------------------------------------------------------------------
# find_track_url
# ---------------------------------------------------------------------------

class TestFindTrackUrl:
    def test_returns_url_on_match(self, monkeypatch):
        monkeypatch.setattr(spotify, "_get_token", lambda: "tok")

        def fake_get(url, **kw):
            return FakeResp({"tracks": {"items": [
                {"external_urls": {"spotify": "https://open.spotify.com/track/abc"}},
            ]}})

        monkeypatch.setattr(spotify.requests, "get", fake_get)
        url = find_track_url("Artist", "Song")
        assert url == "https://open.spotify.com/track/abc"

    def test_returns_none_on_empty_results(self, monkeypatch):
        """A successful search with no items is a definitive 'not on Spotify'."""
        monkeypatch.setattr(spotify, "_get_token", lambda: "tok")
        monkeypatch.setattr(
            spotify.requests, "get",
            lambda url, **kw: FakeResp({"tracks": {"items": []}}),
        )
        assert find_track_url("Nobody", "Nothing") is None

    def test_missing_external_url_returns_none(self, monkeypatch):
        """An item without an external Spotify URL yields None, not a KeyError."""
        monkeypatch.setattr(spotify, "_get_token", lambda: "tok")
        monkeypatch.setattr(
            spotify.requests, "get",
            lambda url, **kw: FakeResp({"tracks": {"items": [{}]}}),
        )
        assert find_track_url("Artist", "Song") is None

    def test_search_http_error_raises_unavailable(self, monkeypatch):
        monkeypatch.setattr(spotify, "_get_token", lambda: "tok")
        monkeypatch.setattr(
            spotify.requests, "get",
            lambda url, **kw: FakeResp(raise_exc=requests.RequestException("boom")),
        )
        with pytest.raises(SpotifyUnavailable):
            find_track_url("Artist", "Song")

    def test_propagates_unavailable_from_token(self, monkeypatch):
        """If the token can't be obtained, find_track_url raises (doesn't return None)."""
        monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_ID", None)
        monkeypatch.setattr(spotify, "SPOTIFY_CLIENT_SECRET", None)
        with pytest.raises(SpotifyUnavailable):
            find_track_url("Artist", "Song")

    def test_passes_artist_and_track_to_query(self, monkeypatch):
        """The search query is scoped by both track and artist fields."""
        monkeypatch.setattr(spotify, "_get_token", lambda: "tok")
        captured = {}

        def fake_get(url, **kw):
            captured["params"] = kw.get("params")
            return FakeResp({"tracks": {"items": []}})

        monkeypatch.setattr(spotify.requests, "get", fake_get)
        find_track_url("Boards of Canada", "Roygbiv")
        q = captured["params"]["q"]
        assert "Roygbiv" in q and "Boards of Canada" in q
