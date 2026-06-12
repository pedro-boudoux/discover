"""
Tier-2 router tests for GET /songs/{track_id}/spotify.

Exercises the DB-cache logic end-to-end through the FastAPI handler:
  - unknown track          → 404
  - cache hit              → stored value, checked=true, Spotify NOT called
  - cache miss + found     → resolves, persists (UPDATE), checked=true
  - cache miss + no match  → persists a definitive null, checked=true
  - cache miss + outage    → no persist, checked=false (retried later)

All DB seams and the Spotify service are monkeypatched; init_db is silenced.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.spotify import SpotifyUnavailable


@pytest.fixture(autouse=True)
def no_init_db(monkeypatch):
    monkeypatch.setattr("app.db.init_db", lambda: None)


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def patch_cursor(monkeypatch, rows):
    """Patch songs.get_cursor with a recording cursor; returns the SQL log.

    Every `with get_cursor()` block in the handler shares `rows` (for the SELECT)
    and appends each execute() to the returned log (so the UPDATE can be asserted).
    """
    log: list[tuple] = []

    @contextmanager
    def _cursor():
        class _Cur:
            def execute(self, sql, params=None):
                log.append((sql, params))

            def fetchone(self):
                return rows[0] if rows else None

            def fetchall(self):
                return list(rows)

        yield _Cur()

    monkeypatch.setattr("app.routers.songs.get_cursor", _cursor)
    return log


def _updated(log) -> bool:
    return any("UPDATE songs SET spotify_url" in sql for sql, _ in log)


class TestSpotifyLinkRouter:
    def test_unknown_track_returns_404(self, monkeypatch, client):
        patch_cursor(monkeypatch, [])
        resp = client.get("/songs/nope/spotify")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_cache_hit_serves_stored_url_without_calling_spotify(self, monkeypatch, client):
        patch_cursor(monkeypatch, [{
            "name": "Song", "artist": "Artist",
            "spotify_url": "https://open.spotify.com/track/cached",
            "spotify_checked_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }])

        def boom(*a, **kw):
            raise AssertionError("Spotify must not be called on a cache hit")

        monkeypatch.setattr("app.routers.songs.spotify.find_track_url", boom)

        resp = client.get("/songs/abc/spotify")
        assert resp.status_code == 200
        assert resp.json() == {
            "url": "https://open.spotify.com/track/cached",
            "checked": True,
        }

    def test_cache_hit_not_on_spotify_returns_null_checked(self, monkeypatch, client):
        """A previously-resolved 'not on Spotify' (url NULL, checked_at set) is honored."""
        patch_cursor(monkeypatch, [{
            "name": "Song", "artist": "Artist",
            "spotify_url": None,
            "spotify_checked_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }])
        monkeypatch.setattr(
            "app.routers.songs.spotify.find_track_url",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not call")),
        )
        resp = client.get("/songs/abc/spotify")
        assert resp.json() == {"url": None, "checked": True}

    def test_cache_miss_resolves_and_persists(self, monkeypatch, client):
        log = patch_cursor(monkeypatch, [{
            "name": "Roygbiv", "artist": "Boards of Canada",
            "spotify_url": None, "spotify_checked_at": None,
        }])
        monkeypatch.setattr(
            "app.routers.songs.spotify.find_track_url",
            lambda artist, name: "https://open.spotify.com/track/found",
        )
        resp = client.get("/songs/abc/spotify")
        assert resp.json() == {
            "url": "https://open.spotify.com/track/found",
            "checked": True,
        }
        assert _updated(log), "a cache miss should persist the resolved link"

    def test_cache_miss_no_match_persists_null(self, monkeypatch, client):
        log = patch_cursor(monkeypatch, [{
            "name": "Obscure", "artist": "Nobody",
            "spotify_url": None, "spotify_checked_at": None,
        }])
        monkeypatch.setattr(
            "app.routers.songs.spotify.find_track_url",
            lambda artist, name: None,
        )
        resp = client.get("/songs/abc/spotify")
        assert resp.json() == {"url": None, "checked": True}
        # A definitive 'not found' is still persisted so we don't re-search.
        assert _updated(log)

    def test_cache_miss_outage_not_persisted(self, monkeypatch, client):
        log = patch_cursor(monkeypatch, [{
            "name": "Song", "artist": "Artist",
            "spotify_url": None, "spotify_checked_at": None,
        }])

        def unavailable(artist, name):
            raise SpotifyUnavailable("network down")

        monkeypatch.setattr("app.routers.songs.spotify.find_track_url", unavailable)

        resp = client.get("/songs/abc/spotify")
        assert resp.json() == {"url": None, "checked": False}
        # Not a definitive answer → must NOT be persisted, so it retries later.
        assert not _updated(log)