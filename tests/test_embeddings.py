"""
Tier-1 unit tests for app/services/embeddings.py.
No database required — get_cursor is monkeypatched where needed.
"""

import hashlib
import math
import pytest
from contextlib import contextmanager

from app.services.embeddings import (
    make_track_id,
    cosine_similarity,
    mmr_rerank,
    build_tag_vector,
    dominant_tags,
    get_or_create_tag_ids,
)


# ---------------------------------------------------------------------------
# get_or_create_tag_ids — must NOT burn SERIAL ids for existing tags
# ---------------------------------------------------------------------------

class _VocabCursor:
    """Fake cursor: SELECT returns an existing id or None; INSERT assigns the
    next id and bumps an insert counter (a proxy for sequence consumption)."""

    def __init__(self, existing, next_id):
        self.existing = dict(existing)
        self.next_id = next_id
        self.insert_count = 0
        self._last = None

    def execute(self, sql, params=()):
        verb = sql.strip().split()[0].upper()
        tag = params[0]
        if verb == "SELECT":
            self._last = {"id": self.existing[tag]} if tag in self.existing else None
        elif verb == "INSERT":
            self.insert_count += 1
            self.existing[tag] = self.next_id
            self._last = {"id": self.next_id}
            self.next_id += 1

    def fetchone(self):
        return self._last


class TestGetOrCreateTagIds:
    def _patch(self, monkeypatch, cursor):
        @contextmanager
        def fake_get_cursor():
            yield cursor
        monkeypatch.setattr("app.services.embeddings.get_cursor", fake_get_cursor)

    def test_existing_tags_do_not_insert(self, monkeypatch):
        """The whole point of the fix: existing tags are pure SELECTs, no INSERT,
        so the SERIAL sequence never advances for them."""
        cur = _VocabCursor(existing={"jazz": 1, "funk": 2}, next_id=300)
        self._patch(monkeypatch, cur)
        ids = get_or_create_tag_ids(["jazz", "funk"])
        assert ids == {"jazz": 1, "funk": 2}
        assert cur.insert_count == 0

    def test_new_tag_inserted_once(self, monkeypatch):
        cur = _VocabCursor(existing={"jazz": 1}, next_id=5)
        self._patch(monkeypatch, cur)
        ids = get_or_create_tag_ids(["jazz", "hyperpop"])
        assert ids["jazz"] == 1
        assert ids["hyperpop"] == 5
        assert cur.insert_count == 1
from app.config import EMBEDDING_DIM
from tests.conftest import make_fake_get_cursor


# ---------------------------------------------------------------------------
# dominant_tags
# ---------------------------------------------------------------------------

class TestDominantTags:
    def _vec(self, slot_to_weight):
        v = [0.0] * EMBEDDING_DIM
        for slot, w in slot_to_weight.items():
            v[slot] = w
        return v

    def test_empty_vectors_returns_empty(self):
        assert dominant_tags([], {1: "jazz"}, top_n=5) == []

    def test_sums_weight_and_counts_songs(self):
        # slot 1 = jazz appears in both songs; slot 2 = funk in one
        vectors = [self._vec({1: 1.0, 2: 0.5}), self._vec({1: 0.5})]
        id_to_tag = {1: "jazz", 2: "funk"}
        out = dominant_tags(vectors, id_to_tag, top_n=5)

        jazz = next(r for r in out if r["tag"] == "jazz")
        funk = next(r for r in out if r["tag"] == "funk")
        assert jazz["weight"] == 1.5 and jazz["count"] == 2
        assert funk["weight"] == 0.5 and funk["count"] == 1
        # jazz (1.5) outranks funk (0.5)
        assert [r["tag"] for r in out] == ["jazz", "funk"]

    def test_share_is_fraction_of_total_weight(self):
        vectors = [self._vec({1: 3.0, 2: 1.0})]
        out = dominant_tags(vectors, {1: "a", 2: "b"}, top_n=5)
        shares = {r["tag"]: r["share"] for r in out}
        assert shares["a"] == 0.75 and shares["b"] == 0.25

    def test_top_n_caps_results(self):
        vectors = [self._vec({1: 0.9, 2: 0.8, 3: 0.7, 4: 0.6})]
        id_to_tag = {1: "a", 2: "b", 3: "c", 4: "d"}
        out = dominant_tags(vectors, id_to_tag, top_n=2)
        assert [r["tag"] for r in out] == ["a", "b"]

    def test_slots_without_a_vocab_tag_are_skipped(self):
        # slot 2 has weight but no entry in id_to_tag → excluded
        vectors = [self._vec({1: 1.0, 2: 0.9})]
        out = dominant_tags(vectors, {1: "a"}, top_n=5)
        assert [r["tag"] for r in out] == ["a"]


# ---------------------------------------------------------------------------
# make_track_id
# ---------------------------------------------------------------------------

class TestMakeTrackId:
    def test_deterministic(self):
        """Same input always produces the same id."""
        assert make_track_id("Artist", "Track") == make_track_id("Artist", "Track")

    def test_length_is_20(self):
        assert len(make_track_id("Burial", "Archangel")) == 20

    def test_case_insensitive(self):
        """Upper, lower, mixed — all produce the same id."""
        assert make_track_id("Burial", "Archangel") == make_track_id("BURIAL", "ARCHANGEL")
        assert make_track_id("Burial", "Archangel") == make_track_id("burial", "archangel")

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is ignored."""
        assert make_track_id("  Burial  ", "  Archangel  ") == make_track_id("Burial", "Archangel")

    def test_different_songs_differ(self):
        id1 = make_track_id("Burial", "Archangel")
        id2 = make_track_id("Burial", "Shell of Light")
        assert id1 != id2

    def test_different_artists_differ(self):
        id1 = make_track_id("Burial", "Archangel")
        id2 = make_track_id("Massive Attack", "Archangel")
        assert id1 != id2

    def test_matches_manual_sha1(self):
        """Verify the exact SHA1 construction."""
        key = "burial|||archangel"
        expected = hashlib.sha1(key.encode()).hexdigest()[:20]
        assert make_track_id("Burial", "Archangel") == expected

    def test_hex_string(self):
        """Result contains only lowercase hex chars."""
        tid = make_track_id("x", "y")
        assert all(c in "0123456789abcdef" for c in tid)


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_zero_vector_a(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_zero_vector_b(self):
        assert cosine_similarity([1.0, 2.0], [0.0, 0.0]) == 0.0

    def test_both_zero_vectors(self):
        assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0

    def test_opposite_vectors(self):
        """Anti-parallel vectors should give -1.0."""
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_known_value(self):
        """[1,1] vs [1,0]: cos = 1/sqrt(2)."""
        assert cosine_similarity([1.0, 1.0], [1.0, 0.0]) == pytest.approx(1.0 / math.sqrt(2))

    def test_symmetry(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        assert cosine_similarity(a, b) == pytest.approx(cosine_similarity(b, a))


# ---------------------------------------------------------------------------
# mmr_rerank
# ---------------------------------------------------------------------------

class TestMmrRerank:
    """
    We use 3-dimensional unit vectors so similarity calculations are easy
    to verify by hand.

    Vector set:
      q  = [1, 0, 0]   (query)
      c0 = [1, 0, 0]   cos(q, c0) = 1.0   (most relevant, identical to query)
      c1 = [0, 1, 0]   cos(q, c1) = 0.0   (orthogonal — diverse)
      c2 = [0.8, 0, 0.6] — less relevant than c0 but similar direction
    """

    @pytest.fixture
    def query(self):
        return [1.0, 0.0, 0.0]

    @pytest.fixture
    def candidates(self):
        return [
            {"id": "c0", "embedding": [1.0, 0.0, 0.0]},
            {"id": "c1", "embedding": [0.0, 1.0, 0.0]},
            {"id": "c2", "embedding": [0.8, 0.0, 0.6]},
        ]

    def test_empty_candidates(self, query):
        assert mmr_rerank(query, [], k=5, lambda_param=0.7) == []

    def test_k_larger_than_pool_returns_all(self, query, candidates):
        result = mmr_rerank(query, candidates, k=100, lambda_param=0.7)
        assert len(result) == len(candidates)

    def test_k_limits_results(self, query, candidates):
        result = mmr_rerank(query, candidates, k=2, lambda_param=0.7)
        assert len(result) == 2

    def test_lambda_1_pure_relevance_order(self, query, candidates):
        """
        With lambda=1.0 (pure relevance) the ranking is by cosine similarity to query:
          c0 (1.0) > c2 (0.8) > c1 (0.0).
        """
        result = mmr_rerank(query, candidates, k=3, lambda_param=1.0)
        ids = [r["id"] for r in result]
        assert ids == ["c0", "c2", "c1"]

    def test_lambda_0_pure_diversity(self, query, candidates):
        """
        With lambda=0.0 the MMR score is purely -redundancy, so after picking the
        first candidate (arbitrarily c0, highest relevance breaks the tie in the
        very first iteration when selected is empty and redundancy=0 for all),
        subsequent picks maximize distance from already-selected items.

        After c0=[1,0,0] is picked:
          c1: score = 0 * 0.0 - 1.0 * cos(c1, c0) = -cos([0,1,0],[1,0,0]) = 0.0
          c2: score = 0 * 0.0 - 1.0 * cos(c2, c0) = -0.8

        So c1 should be chosen second (less redundant with c0 than c2 is).
        """
        result = mmr_rerank(query, candidates, k=3, lambda_param=0.0)
        # c0 is first (all scores equal 0 on first iteration, but c0 has highest relevance
        # since tie-break still uses lambda*rel = 0 for all; in practice the loop finds the
        # first candidate in list order with max score — c0 has same score as others,
        # first-found wins, so c0 is first).
        # The key assertion is that c1 (diversity winner) comes before c2.
        ids = [r["id"] for r in result]
        assert ids[0] == "c0"
        assert ids[1] == "c1"
        assert ids[2] == "c2"

    def test_result_items_are_from_candidates(self, query, candidates):
        """All returned dicts are original candidate objects."""
        result = mmr_rerank(query, candidates, k=3, lambda_param=0.7)
        assert all(r in candidates for r in result)

    def test_k_equals_zero_returns_empty(self, query, candidates):
        result = mmr_rerank(query, candidates, k=0, lambda_param=0.7)
        assert result == []


# ---------------------------------------------------------------------------
# build_tag_vector
# ---------------------------------------------------------------------------

class TestBuildTagVector:
    def test_empty_dict_returns_all_zeros(self):
        """No DB call needed — empty guard is hit first."""
        result = build_tag_vector({})
        assert len(result) == EMBEDDING_DIM
        assert all(v == 0.0 for v in result)

    def test_normalization_top_tag_equals_one(self, monkeypatch):
        """The tag with the highest count maps to 1.0."""
        vocab = [{"id": 0, "tag": "rock"}, {"id": 1, "tag": "indie"}]
        monkeypatch.setattr("app.services.embeddings.get_cursor", make_fake_get_cursor(vocab))

        result = build_tag_vector({"rock": 100, "indie": 50})
        assert result[0] == pytest.approx(1.0)   # rock → slot 0, count/max = 100/100
        assert result[1] == pytest.approx(0.5)   # indie → slot 1, count/max = 50/100

    def test_tag_not_in_vocab_is_ignored(self, monkeypatch):
        """Tags absent from the vocab produce no change in the vector."""
        vocab = [{"id": 0, "tag": "ambient"}]
        monkeypatch.setattr("app.services.embeddings.get_cursor", make_fake_get_cursor(vocab))

        result = build_tag_vector({"ambient": 80, "unknown_tag": 200})
        # ambient is in vocab → slot 0 = 1.0 (max is 200 from unknown_tag? No —
        # normalization uses max of *all* tag_counts values including unknown ones)
        # max_count = 200, ambient in vocab → vector[0] = 80/200 = 0.4
        assert result[0] == pytest.approx(0.4)
        # unknown_tag not in vocab → no slot → all other slots 0
        assert result[1] == 0.0

    def test_tags_beyond_embedding_dim_dropped(self, monkeypatch):
        """Tags whose vocab id >= EMBEDDING_DIM are silently dropped."""
        # id == EMBEDDING_DIM is the boundary that gets dropped
        vocab = [
            {"id": 0, "tag": "jazz"},
            {"id": EMBEDDING_DIM, "tag": "outofbounds"},
        ]
        monkeypatch.setattr("app.services.embeddings.get_cursor", make_fake_get_cursor(vocab))

        result = build_tag_vector({"jazz": 50, "outofbounds": 100})
        assert len(result) == EMBEDDING_DIM
        # jazz → slot 0 = 50/100 = 0.5
        assert result[0] == pytest.approx(0.5)
        # outofbounds has id == EMBEDDING_DIM → dropped (condition is `< EMBEDDING_DIM`)
        # no IndexError; vector length stays at EMBEDDING_DIM

    def test_vector_length_is_embedding_dim(self, monkeypatch):
        vocab = [{"id": 5, "tag": "drone"}]
        monkeypatch.setattr("app.services.embeddings.get_cursor", make_fake_get_cursor(vocab))

        result = build_tag_vector({"drone": 42})
        assert len(result) == EMBEDDING_DIM

    def test_single_tag_normalizes_to_one(self, monkeypatch):
        """Single tag → max_count equals its count → 1.0."""
        vocab = [{"id": 3, "tag": "ambient"}]
        monkeypatch.setattr("app.services.embeddings.get_cursor", make_fake_get_cursor(vocab))

        result = build_tag_vector({"ambient": 77})
        assert result[3] == pytest.approx(1.0)
        # all other slots are 0
        assert sum(v for i, v in enumerate(result) if i != 3) == pytest.approx(0.0)
