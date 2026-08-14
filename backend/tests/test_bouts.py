"""Bout construction and review flagging (D7, D8)."""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.bouts import build_bouts
from app.serving.predictor import CLASSES

DNS = CLASSES.index("DNS")
WAK = CLASSES.index("WAK")
STDUP = CLASSES.index("STDUP")
N = len(CLASSES)

DEFAULT_MARGIN = 0.15
DEFAULT_LOW_CONFIDENCE = 0.60


def _confident_probs(label: int, n_windows: int, confidence: float = 0.9) -> np.ndarray:
    """``n_windows`` rows, each a clean one-hot-ish distribution favouring ``label``."""
    remainder = (1.0 - confidence) / (N - 1)
    row = np.full(N, remainder)
    row[label] = confidence
    return np.tile(row, (n_windows, 1))


def test_adjacent_same_label_windows_merge_into_one_bout():
    labels = np.array([WAK, WAK, WAK, DNS, DNS])
    probs = np.vstack([_confident_probs(WAK, 3), _confident_probs(DNS, 2)])

    bouts = build_bouts(
        "s1",
        labels,
        probs,
        dns_wak_margin=DEFAULT_MARGIN,
        low_confidence_threshold=DEFAULT_LOW_CONFIDENCE,
    )

    assert len(bouts) == 2
    assert bouts[0].task == "WAK"
    assert bouts[0].window_count == 3
    assert bouts[1].task == "DNS"
    assert bouts[1].window_count == 2


def test_bout_boundaries_advance_monotonically_in_time():
    # Windows overlap 50% (D4's window/step geometry), so a bout's end_ms (from its last
    # window's own end) legitimately overlaps the next bout's start_ms (from its first window's
    # own start) -- they are not expected to meet exactly. What must hold is that time advances.
    labels = np.array([WAK, WAK, DNS, DNS])
    probs = np.vstack([_confident_probs(WAK, 2), _confident_probs(DNS, 2)])

    bouts = build_bouts(
        "s1",
        labels,
        probs,
        dns_wak_margin=DEFAULT_MARGIN,
        low_confidence_threshold=DEFAULT_LOW_CONFIDENCE,
    )

    assert bouts[0].start_ms < bouts[0].end_ms
    assert bouts[1].start_ms < bouts[1].end_ms
    assert bouts[1].start_ms > bouts[0].start_ms


def test_low_confidence_bout_is_flagged():
    labels = np.array([DNS, DNS, DNS])
    probs = _confident_probs(DNS, 3, confidence=0.4)  # below the 0.60 threshold

    bouts = build_bouts(
        "s1",
        labels,
        probs,
        dns_wak_margin=DEFAULT_MARGIN,
        low_confidence_threshold=DEFAULT_LOW_CONFIDENCE,
    )

    assert bouts[0].flagged is True
    assert "low_confidence" in bouts[0].flag_reasons


def test_narrow_dns_wak_margin_is_flagged():
    # A DNS bout the model is confident about overall, but where DNS and WAK are nearly tied.
    row = np.zeros(N)
    row[DNS] = 0.42
    row[WAK] = 0.40
    remaining = (1.0 - 0.82) / (N - 2)
    for i in range(N):
        if i not in (DNS, WAK):
            row[i] = remaining
    probs = np.tile(row, (3, 1))
    labels = np.array([DNS, DNS, DNS])

    bouts = build_bouts(
        "s1",
        labels,
        probs,
        dns_wak_margin=DEFAULT_MARGIN,
        low_confidence_threshold=DEFAULT_LOW_CONFIDENCE,
    )

    assert bouts[0].flagged is True
    assert "dns_wak_margin" in bouts[0].flag_reasons


def test_a_clean_confident_bout_is_not_flagged():
    # _confident_probs spreads its remainder evenly across every other class, so DNS and WAK
    # always land exactly tied -- a margin of 0, which would always flag. Build an explicit
    # vector instead, with DNS and WAK clearly separated as well as a high winning class.
    row = np.array([0.30, 0.65, 0.02, 0.03])  # DNS, STDUP, UPS, WAK
    assert CLASSES == ("DNS", "STDUP", "UPS", "WAK")
    probs = np.tile(row, (3, 1))
    labels = np.array([STDUP, STDUP, STDUP])

    bouts = build_bouts(
        "s1",
        labels,
        probs,
        dns_wak_margin=DEFAULT_MARGIN,
        low_confidence_threshold=DEFAULT_LOW_CONFIDENCE,
    )

    assert bouts[0].flagged is False
    assert bouts[0].flag_reasons == ()


def test_empty_session_yields_no_bouts():
    bouts = build_bouts(
        "s1",
        np.array([], dtype=np.int64),
        np.empty((0, N)),
        dns_wak_margin=DEFAULT_MARGIN,
        low_confidence_threshold=DEFAULT_LOW_CONFIDENCE,
    )
    assert bouts == []


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError, match="different numbers of windows"):
        build_bouts(
            "s1",
            np.array([DNS, DNS]),
            _confident_probs(DNS, 3),
            dns_wak_margin=DEFAULT_MARGIN,
            low_confidence_threshold=DEFAULT_LOW_CONFIDENCE,
        )
