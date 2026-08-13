"""The montage contract rejects, and names what it rejected."""

from __future__ import annotations

import pytest

from app.domain.montage import MONTAGE, N_CHANNELS, conforms, validate_montage


def test_the_exact_montage_conforms():
    assert conforms(list(MONTAGE))
    assert validate_montage(list(MONTAGE)) == []


def test_a_reordered_montage_is_rejected_as_reordered_not_unknown():
    """Swapping two real channels must read as an order problem, which is fixable in an export
    setting, rather than as an unknown channel, which is a different electrode set."""
    columns = list(MONTAGE)
    columns[1], columns[2] = columns[2], columns[1]

    violations = validate_montage(columns)

    assert violations, "a reordered montage must not pass"
    assert {v.reason for v in violations} == {"channel_out_of_order"}
    assert {v.position for v in violations} == {1, 2}


def test_a_near_miss_name_is_rejected_rather_than_guessed():
    """The whole argument for refusing fuzzy matching: this is one character from a real channel
    and must still be refused, because guessing produces a silently wrong montage."""
    columns = list(MONTAGE)
    columns[8] = "sEMG: soleus "  # trailing space

    violations = validate_montage(columns)

    assert len(violations) == 1
    assert violations[0].reason == "channel_unknown"
    assert violations[0].expected == "sEMG: soleus"
    assert violations[0].received == "sEMG: soleus "


def test_enabl3s_shaped_input_is_rejected():
    """The thesis's second corpus has seven channels. Shipping it would require bending the
    contract, so the contract must visibly refuse it."""
    violations = validate_montage(list(MONTAGE[:7]))

    reasons = {v.reason for v in violations}
    assert "channel_count" in reasons
    assert "channel_missing" in reasons


def test_extra_channels_are_reported_individually():
    violations = validate_montage([*MONTAGE, "sEMG: gluteus medius", "IMU: shank"])

    unexpected = [v for v in violations if v.reason == "channel_unexpected"]
    assert {v.received for v in unexpected} == {"sEMG: gluteus medius", "IMU: shank"}


def test_every_violation_is_reported_not_just_the_first():
    """A user fixing an export should get the whole list in one pass."""
    violations = validate_montage(["wrong"] * N_CHANNELS)
    assert len(violations) == N_CHANNELS


@pytest.mark.parametrize("columns", [[], ["sEMG: soleus"]])
def test_short_input_is_rejected(columns):
    assert not conforms(columns)
