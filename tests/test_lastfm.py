"""
Tier-1 unit tests for app/services/lastfm.py — pure dict math only.
blend_tags has no I/O; no mocking required.
"""

import pytest

from app.services.lastfm import blend_tags


class TestBlendTags:
    """
    blend_tags(artist_tags, track_tags, similar_artist_tags=None,
               artist_weight=0.3, similar_weight=0.1)

    Rules (from source):
      1. artist_tags scaled by artist_weight using int() (floor truncation).
      2. similar_artist_tags: contribution = int(count * similar_weight * match),
         summed per tag.
      3. track_tags added at full weight (no scaling).
      4. Final dict keeps only entries with count > 0.
    """

    def test_track_tags_full_weight(self):
        """Track tags are added without any scaling."""
        result = blend_tags(
            artist_tags={},
            track_tags={"shoegaze": 50, "dream pop": 30},
        )
        assert result == {"shoegaze": 50, "dream pop": 30}

    def test_artist_tags_scaled_by_weight(self):
        """Artist tags use int(count * 0.3) — floor truncation."""
        result = blend_tags(
            artist_tags={"rock": 100, "indie": 50},
            track_tags={},
        )
        # int(100 * 0.3) = 30, int(50 * 0.3) = 15
        assert result["rock"] == 30
        assert result["indie"] == 15

    def test_artist_weight_truncation(self):
        """Verify floor (int) truncation, not rounding."""
        # int(10 * 0.3) = int(3.0) = 3
        # int(7 * 0.3) = int(2.1) = 2
        result = blend_tags(
            artist_tags={"a": 10, "b": 7},
            track_tags={},
        )
        assert result["a"] == 3
        assert result["b"] == 2

    def test_track_tags_override_accumulate_on_artist_tags(self):
        """Tags shared between artist and track are summed."""
        result = blend_tags(
            artist_tags={"rock": 100},   # → int(30)
            track_tags={"rock": 20},     # + 20
        )
        assert result["rock"] == 50       # 30 + 20

    def test_similar_artist_tags_contribute(self):
        """
        similar_artist_tags is a list of (tag_dict, match_score) tuples.
        contribution per tag = int(count * similar_weight * match).
        """
        similar = [
            ({"ambient": 100}, 0.8),   # int(100 * 0.1 * 0.8) = int(8.0) = 8
            ({"ambient": 50}, 0.6),    # int(50  * 0.1 * 0.6) = int(3.0) = 3
        ]
        result = blend_tags(
            artist_tags={},
            track_tags={},
            similar_artist_tags=similar,
        )
        assert result.get("ambient") == 11   # 8 + 3

    def test_similar_tags_truncate(self):
        """int() floors the similar contribution."""
        # int(10 * 0.1 * 0.9) = int(0.9) = 0  → dropped (count <= 0)
        similar = [({"niche": 10}, 0.9)]
        result = blend_tags(
            artist_tags={},
            track_tags={},
            similar_artist_tags=similar,
        )
        assert "niche" not in result

    def test_zero_count_entries_dropped(self):
        """Entries with count <= 0 are not returned."""
        # artist_tags: int(1 * 0.3) = 0, track_tags: no entry for this tag
        # → the tag starts at 0 and never accumulates
        result = blend_tags(
            artist_tags={"tiny": 1},    # int(1 * 0.3) = 0
            track_tags={},
        )
        assert "tiny" not in result

    def test_no_similar_tags_none(self):
        """similar_artist_tags=None is treated the same as no similar tags."""
        result = blend_tags(
            artist_tags={"jazz": 100},
            track_tags={"jazz": 10},
            similar_artist_tags=None,
        )
        assert result["jazz"] == 40   # int(30) + 10

    def test_all_sources_combined(self):
        """
        Hand-computed blend with all three sources present.

          artist_tags:  rock=100 → int(30)
          track_tags:   rock=25
          similar:      ({"rock": 80}, 1.0) → int(80 * 0.1 * 1.0) = 8
          total rock = 30 + 25 + 8 = 63

          artist_tags:  indie=50 → int(15)  (no track or similar contribution)
          total indie = 15
        """
        similar = [({"rock": 80}, 1.0)]
        result = blend_tags(
            artist_tags={"rock": 100, "indie": 50},
            track_tags={"rock": 25},
            similar_artist_tags=similar,
        )
        assert result["rock"] == 63
        assert result["indie"] == 15

    def test_empty_inputs_returns_empty(self):
        result = blend_tags(artist_tags={}, track_tags={}, similar_artist_tags=[])
        assert result == {}

    def test_custom_artist_weight(self):
        """artist_weight parameter is respected."""
        result = blend_tags(
            artist_tags={"post-rock": 100},
            track_tags={},
            artist_weight=0.5,
        )
        assert result["post-rock"] == 50   # int(100 * 0.5)

    def test_custom_similar_weight(self):
        """similar_weight parameter is respected."""
        similar = [({"drone": 100}, 1.0)]
        result = blend_tags(
            artist_tags={},
            track_tags={},
            similar_artist_tags=similar,
            similar_weight=0.2,
        )
        assert result["drone"] == 20   # int(100 * 0.2 * 1.0)

    def test_result_values_are_integers(self):
        """All blended values must be int (the source uses int() throughout)."""
        similar = [({"x": 77}, 0.9)]
        result = blend_tags(
            artist_tags={"x": 50},
            track_tags={"x": 10},
            similar_artist_tags=similar,
        )
        for v in result.values():
            assert isinstance(v, int)
