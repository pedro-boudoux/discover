"""
Tier-1 unit tests for app/services/steering.py.

apply_steering calls get_rejected_embeddings which hits the DB.
We monkeypatch steering.get_rejected_embeddings directly so no DB is needed.

IMPORTANT BEHAVIORAL NOTE (asymmetry — do NOT fix the source):
  - When there are NO rejected embeddings, apply_steering returns
    base.tolist() WITHOUT L2-normalizing.
  - When there ARE rejected embeddings, the result IS L2-normalized.
  This asymmetry is documented in the tests and in the final report.
"""

import math
import pytest
import numpy as np

from app.services.steering import apply_steering
from app.config import STEERING_ALPHA
import app.services.steering as steering_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def l2_norm(vec: list) -> float:
    return math.sqrt(sum(x * x for x in vec))


def is_unit_vector(vec: list, tol: float = 1e-6) -> bool:
    return abs(l2_norm(vec) - 1.0) < tol


# ---------------------------------------------------------------------------
# apply_steering — no-reject path
# ---------------------------------------------------------------------------

class TestApplySteeringNoRejects:
    def test_returns_base_unchanged_when_no_rejects(self, monkeypatch):
        """With no rejected embeddings the base vector is returned as-is."""
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: [])

        base = [0.1, 0.5, 0.3]
        result = apply_steering(base, "seed_abc")
        assert result == pytest.approx(base)

    def test_no_reject_result_is_not_normalized(self, monkeypatch):
        """
        ASYMMETRY NOTE: The no-reject path does NOT L2-normalize.
        base = [3.0, 4.0] has norm 5.0, not 1.0 — and is returned as-is.
        This is distinct from the reject path, which always normalizes.
        """
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: [])

        base = [3.0, 4.0]   # norm = 5.0
        result = apply_steering(base, "seed_abc")

        assert l2_norm(result) == pytest.approx(5.0)
        assert not is_unit_vector(result)

    def test_no_reject_returns_list(self, monkeypatch):
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: [])

        result = apply_steering([1.0, 0.0], "seed_xyz")
        assert isinstance(result, list)

    def test_seed_id_passed_to_get_rejected(self, monkeypatch):
        """The seed_track_id is forwarded to get_rejected_embeddings."""
        captured = []

        def fake_rejected(sid):
            captured.append(sid)
            return []

        monkeypatch.setattr(steering_module, "get_rejected_embeddings", fake_rejected)
        apply_steering([1.0, 0.0], "my_seed_id")
        assert captured == ["my_seed_id"]


# ---------------------------------------------------------------------------
# apply_steering — with-reject path
# ---------------------------------------------------------------------------

class TestApplySteeringWithRejects:
    def test_result_is_l2_normalized(self, monkeypatch):
        """
        When rejected embeddings exist, the result is L2-normalized to unit length.
        This contrasts with the no-reject path which returns unnormalized.
        """
        rejected = [[0.0, 1.0, 0.0]]
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: rejected)

        base = [1.0, 0.5, 0.0]
        result = apply_steering(base, "seed_001")
        assert is_unit_vector(result)

    def test_steering_direction_away_from_reject(self, monkeypatch):
        """
        base = [1.0, 0.0], reject = [0.0, 1.0]
        steered = base - STEERING_ALPHA * reject
                = [1.0, -STEERING_ALPHA]
        normalized.
        """
        reject = [[0.0, 1.0]]
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: reject)

        base = [1.0, 0.0]
        result = apply_steering(base, "seed")

        expected_raw = np.array([1.0, 0.0]) - STEERING_ALPHA * np.array([0.0, 1.0])
        expected_norm = expected_raw / np.linalg.norm(expected_raw)
        assert result == pytest.approx(expected_norm.tolist(), abs=1e-6)

    def test_multiple_rejects_summed(self, monkeypatch):
        """
        Multiple rejected vectors are all added to the steering term:
          steering = ALPHA * (rej0 + rej1 + ...)
        """
        rejected = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: rejected)

        base = [0.0, 0.0, 1.0]
        result = apply_steering(base, "seed")

        rej_sum = np.array([1.0, 0.0, 0.0]) + np.array([0.0, 1.0, 0.0])
        expected_raw = np.array([0.0, 0.0, 1.0]) - STEERING_ALPHA * rej_sum
        expected_norm = expected_raw / np.linalg.norm(expected_raw)
        assert result == pytest.approx(expected_norm.tolist(), abs=1e-6)

    def test_result_is_list(self, monkeypatch):
        rejected = [[1.0, 0.0]]
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: rejected)

        result = apply_steering([0.5, 0.5], "seed")
        assert isinstance(result, list)

    def test_norm_zero_guard(self, monkeypatch):
        """
        If the steered vector has norm 0, the source returns the unnormalized
        zero vector rather than dividing by zero.
        """
        # base = [0.3, 0.0], reject = [1.0, 0.0] with ALPHA=0.3
        # steered = [0.3, 0.0] - 0.3*[1.0, 0.0] = [0.0, 0.0]  → norm == 0
        rejected = [[1.0, 0.0]]
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: rejected)

        result = apply_steering([STEERING_ALPHA, 0.0], "seed")
        # Should not raise; result is the zero vector
        assert result == pytest.approx([0.0, 0.0], abs=1e-9)

    def test_steering_alpha_constant_used(self, monkeypatch):
        """Ensure STEERING_ALPHA from config drives the magnitude of steering."""
        reject = [[1.0, 0.0, 0.0]]
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: reject)

        base = np.array([2.0, 1.0, 0.0])
        result = apply_steering(base.tolist(), "seed")

        expected_raw = base - STEERING_ALPHA * np.array([1.0, 0.0, 0.0])
        expected_norm = expected_raw / np.linalg.norm(expected_raw)
        assert result == pytest.approx(expected_norm.tolist(), abs=1e-6)


# ---------------------------------------------------------------------------
# Asymmetry documentation test
# ---------------------------------------------------------------------------

class TestSteeringNormalizationAsymmetry:
    """
    Documents the normalization asymmetry between the two paths in apply_steering.

    Source (steering.py, lines 22-38):
        if not rejected:
            return base.tolist()              # <- NOT normalized
        ...
        result = result / norm if norm > 0 else result
        return result.tolist()                # <- normalized

    This means callers who depend on a unit-vector output will get it only
    when there are rejections, not on a cold start.
    """

    def test_no_reject_path_is_unnormalized(self, monkeypatch):
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: [])
        base = [1.0, 2.0, 3.0]
        result = apply_steering(base, "seed")
        # Not a unit vector
        assert l2_norm(result) == pytest.approx(l2_norm(base))

    def test_reject_path_is_normalized(self, monkeypatch):
        rejected = [[0.0, 0.0, 1.0]]
        monkeypatch.setattr(steering_module, "get_rejected_embeddings", lambda sid: rejected)
        base = [1.0, 2.0, 3.0]
        result = apply_steering(base, "seed")
        assert is_unit_vector(result)
