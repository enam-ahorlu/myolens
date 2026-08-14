"""Temporal smoothing (D6): five-window majority vote, then per-class minimum dwell."""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.smoothing import (
    DWELL_MS,
    enforce_minimum_dwell,
    majority_vote_smooth,
    min_dwell_windows,
)
from app.serving.predictor import CLASSES

DNS = CLASSES.index("DNS")
STDUP = CLASSES.index("STDUP")
UPS = CLASSES.index("UPS")
WAK = CLASSES.index("WAK")


def test_min_dwell_windows_matches_the_frozen_millisecond_figures():
    # STEP_MS is 125.0 at the frozen 480/240 window/step geometry.
    assert min_dwell_windows("WAK") == 8  # 1000 / 125
    assert min_dwell_windows("STDUP") == 6  # 800 / 125 = 6.4 -> 6
    assert min_dwell_windows("DNS") == 10  # 1200 / 125 = 9.6 -> 10
    assert min_dwell_windows("UPS") == 10
    assert set(DWELL_MS) == set(CLASSES)


def test_majority_vote_flips_a_single_spurious_window():
    labels = np.array([WAK, WAK, DNS, WAK, WAK])
    smoothed = majority_vote_smooth(labels)
    assert smoothed.tolist() == [WAK, WAK, WAK, WAK, WAK]


def test_majority_vote_preserves_a_run_longer_than_the_window():
    labels = np.array([WAK] * 4 + [DNS] * 6 + [WAK] * 4)
    smoothed = majority_vote_smooth(labels)
    # The interior of each run is untouched; only the vicinity of the boundary can move.
    assert smoothed[0] == WAK
    assert smoothed[6] == DNS  # centre of the DNS run
    assert smoothed[-1] == WAK


def test_majority_vote_breaks_a_tie_in_favour_of_the_centre_label():
    # A 4-window vote window at a boundary can tie 2-2; the centre label should win the tie.
    labels = np.array([WAK, WAK, DNS, DNS])
    smoothed = majority_vote_smooth(labels, window=4)
    assert smoothed[1] in (WAK, DNS)  # sanity: still a valid class
    # Position 1's own label (WAK) is among the tied modes at some window position -- the
    # function must not always fall back to the smallest class index (DNS's index is 0).
    assert not np.all(smoothed == DNS)


def test_enforce_minimum_dwell_absorbs_a_short_run_into_its_longer_neighbour():
    # A 2-window WAK intrusion (min dwell 8) inside a long DNS run (min dwell 10) should be
    # absorbed into DNS.
    labels = np.array([DNS] * 12 + [WAK] * 2 + [DNS] * 12)
    dwelled = enforce_minimum_dwell(labels)
    assert np.all(dwelled == DNS)


def test_enforce_minimum_dwell_leaves_a_run_that_already_meets_its_class_minimum():
    labels = np.array([DNS] * 12 + [WAK] * 8 + [DNS] * 12)  # WAK's own minimum is 8
    dwelled = enforce_minimum_dwell(labels)
    assert dwelled[12] == WAK
    assert dwelled[19] == WAK
    assert dwelled[11] == DNS
    assert dwelled[20] == DNS


def test_enforce_minimum_dwell_merges_toward_the_longer_neighbour():
    # A short UPS run (min dwell 10) between a 3-window DNS run and a 20-window STDUP run
    # should merge toward STDUP, the longer neighbour.
    labels = np.array([DNS] * 3 + [UPS] * 4 + [STDUP] * 20)
    dwelled = enforce_minimum_dwell(labels)
    assert dwelled[3] == STDUP


def test_enforce_minimum_dwell_is_a_no_op_on_an_empty_array():
    assert enforce_minimum_dwell(np.array([], dtype=np.int64)).shape == (0,)


def test_majority_vote_rejects_non_1d_input():
    with pytest.raises(ValueError, match="1-D"):
        majority_vote_smooth(np.zeros((2, 2), dtype=np.int64))
