"""Refusals are typed, specific, and never leak a trace."""

from __future__ import annotations

from app.errors import (
    ErrorCode,
    MontageRejected,
    NotCalibrated,
    OutOfDistribution,
    SegmentationNotApproved,
    SessionTooLong,
)


def test_montage_rejection_carries_the_specific_violations():
    error = MontageRejected([{"reason": "channel_out_of_order", "position": 2}])
    envelope = error.envelope("req-1")

    assert error.status_code == 409
    assert envelope.code is ErrorCode.MONTAGE_REJECTED
    assert envelope.details[0]["position"] == 2
    assert "guess" in envelope.message


def test_out_of_distribution_reports_the_distance_and_the_threshold():
    """A refusal a user cannot interrogate is indistinguishable from a bug."""
    envelope = OutOfDistribution(distance=18.4321, threshold=12.0).envelope()

    assert envelope.code is ErrorCode.OUT_OF_DISTRIBUTION
    assert envelope.details[0]["mahalanobis"] == 18.4321
    assert envelope.details[0]["threshold"] == 12.0


def test_the_approval_gate_refuses_with_412_and_says_why():
    error = SegmentationNotApproved("sess-1", flagged_bouts=3)

    assert error.status_code == 412
    assert "locked until" in error.message
    assert error.details[0]["flagged_bouts"] == 3


def test_missing_calibration_is_a_precondition_failure_not_a_not_found():
    assert NotCalibrated("p-1").status_code == 412


def test_an_oversized_session_states_the_cap():
    error = SessionTooLong(seconds=754.2, cap_seconds=600)
    assert error.status_code == 413
    assert "600" in error.message
