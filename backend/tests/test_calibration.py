"""Per-task calibration, the %CAL reference, and the OOD guard."""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.calibration import (
    assess,
    calibrated_tasks,
    difficulty_band,
    envelope_peak,
    mahalanobis_distance,
)
from app.serving.predictor import CLASSES


def test_every_class_is_reported_even_when_absent():
    """An absent task and an unmentioned task look identical in a dict and are completely
    different clinically, so the output space is always the full class list."""
    result = assess({"WAK": (30, 3)}, min_windows=20, min_blocks=3)

    assert set(result) == set(CLASSES)
    assert result["DNS"].status == "not_attempted"


def test_sufficiency_needs_both_the_window_count_and_the_block_count():
    """The thesis measured the crossover: ~20 windows spread across the session beat ~50
    contiguous ones. Blocks are not a formality."""
    result = assess({"WAK": (30, 1), "UPS": (12, 3), "DNS": (30, 3)}, 20, 3)

    assert result["WAK"].status == "insufficient"  # enough windows, one block
    assert result["UPS"].status == "insufficient"  # enough blocks, too few windows
    assert result["DNS"].status == "calibrated"


def test_the_output_space_is_restricted_to_calibrated_tasks():
    """A participant who cannot safely descend stairs must not have DNS predicted for them."""
    result = assess({"WAK": (30, 3), "STDUP": (25, 3), "DNS": (4, 1)}, 20, 3)

    assert set(calibrated_tasks(result)) == {"WAK", "STDUP"}
    assert "DNS" not in calibrated_tasks(result)


def test_the_cal_reference_ignores_a_single_sample_artefact():
    """A cable knock must not become the denominator for the whole session."""
    envelope = np.ones((200, 1))
    envelope[100, 0] = 1000.0

    peak = envelope_peak(envelope)

    assert peak[0] < 10.0


def test_an_empty_calibration_cannot_produce_a_reference():
    with pytest.raises(ValueError):
        envelope_peak(np.zeros((0, 9)))


def test_mahalanobis_distance_is_zero_at_the_distribution_mean():
    mean = np.zeros(4)
    identity = np.eye(4)
    assert mahalanobis_distance(np.zeros((5, 4)), mean, identity) == pytest.approx(0.0)


def test_mahalanobis_distance_grows_with_displacement():
    mean = np.zeros(4)
    identity = np.eye(4)
    near = mahalanobis_distance(np.ones((5, 4)), mean, identity)
    far = mahalanobis_distance(np.full((5, 4), 3.0), mean, identity)
    assert far > near > 0


def test_difficulty_bands_partition_the_range_below_the_refusal_threshold():
    assert difficulty_band(1.0, 12.0) == "typical"
    assert difficulty_band(7.0, 12.0) == "moderate"
    assert difficulty_band(11.0, 12.0) == "atypical"
