"""Metrics, and the null co-contraction case the plan names as a required test.

TODO(TD-06): these fixtures are hand-built rather than drawn from the demonstration recordings,
but the integration tests share fixtures with the shipped demo data, so a quirk of those three
held-out subjects could be encoded as an expectation rather than a requirement.
Prudent & inadvertent — using real held-out data was the cheapest way to get realistic
behaviour and the trade was accepted knowingly. Impact: Low.
Repayment: v1.1, synthetic fixtures generated at the boundary conditions.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.metrics import (
    ACTIVITY_THRESHOLD,
    co_contraction_index,
    correction_rate,
    duty_cycle,
    group_mean,
    percent_cal,
)

THRESHOLD_PCT = ACTIVITY_THRESHOLD * 100.0


class TestCoContractionIndex:
    def test_perfectly_matched_groups_give_100(self):
        """2*min(A,B)/(A+B) is 1 when A == B. Complete co-contraction."""
        agonist = np.array([50.0, 60.0, 70.0])
        result = co_contraction_index(agonist, agonist.copy())

        assert result.value == pytest.approx(100.0)
        assert result.windows_used == 3

    def test_a_silent_antagonist_gives_near_zero(self):
        """One group working alone is a finding, and it is not the same as no data."""
        agonist = np.array([80.0, 90.0, 85.0])
        antagonist = np.array([0.0, 0.0, 0.0])

        result = co_contraction_index(agonist, antagonist)

        assert result.value == pytest.approx(0.0)
        assert result.windows_used == 3
        assert not result.is_null

    def test_both_groups_below_threshold_is_null_not_zero(self):
        """THE named edge case. At rest, the ratio is still arithmetically defined and is
        dominated entirely by the relative size of two noise floors — so a resting limb would
        report as strongly co-contracting. Null says 'no answer'; zero would say 'no
        co-contraction', which is a clinical claim we have no basis for."""
        below = THRESHOLD_PCT - 1.0
        agonist = np.array([below, below, below])
        antagonist = np.array([below, below, below])

        result = co_contraction_index(agonist, antagonist)

        assert result.is_null
        assert result.value is None
        assert result.windows_used == 0
        assert result.windows_total == 3

    def test_a_window_qualifies_when_either_group_is_active(self):
        below = THRESHOLD_PCT - 1.0
        agonist = np.array([below, 90.0, below])
        antagonist = np.array([below, 10.0, below])

        result = co_contraction_index(agonist, antagonist)

        assert result.windows_used == 1
        assert result.windows_total == 3
        assert result.value == pytest.approx(2 * 10.0 / 100.0 * 100.0)

    def test_no_windows_at_all_is_null(self):
        result = co_contraction_index(np.array([]), np.array([]))
        assert result.is_null
        assert result.windows_total == 0

    def test_non_finite_windows_are_excluded_rather_than_propagated(self):
        """A failed electrode must not turn an entire session's CCI into NaN."""
        agonist = np.array([50.0, np.nan, 50.0])
        antagonist = np.array([50.0, 50.0, 50.0])

        result = co_contraction_index(agonist, antagonist)

        assert result.value == pytest.approx(100.0)
        assert result.windows_used == 2

    def test_the_index_is_symmetric_in_its_arguments(self):
        a = np.array([70.0, 40.0, 55.0])
        b = np.array([30.0, 80.0, 20.0])
        assert co_contraction_index(a, b).value == pytest.approx(co_contraction_index(b, a).value)

    def test_mismatched_lengths_are_a_programming_error(self):
        with pytest.raises(ValueError):
            co_contraction_index(np.array([1.0, 2.0]), np.array([1.0]))


class TestPercentCal:
    def test_amplitude_is_expressed_against_the_participants_own_peak(self):
        envelope = np.array([[0.5, 1.0], [0.25, 0.5]])
        peak = np.array([1.0, 2.0])

        result = percent_cal(envelope, peak)

        np.testing.assert_allclose(result, [[50.0, 50.0], [25.0, 25.0]])

    def test_a_dead_channel_yields_nan_rather_than_infinity(self):
        """A zero calibration peak means a failed electrode. Infinity would propagate silently
        through every downstream mean; NaN propagates loudly and is filtered explicitly."""
        envelope = np.array([[1.0, 1.0]])
        peak = np.array([2.0, 0.0])

        result = percent_cal(envelope, peak)

        assert result[0, 0] == pytest.approx(50.0)
        assert np.isnan(result[0, 1])

    def test_a_shape_mismatch_is_rejected(self):
        with pytest.raises(ValueError):
            percent_cal(np.zeros((3, 9)), np.zeros(4))


class TestDutyCycle:
    def test_duty_cycle_counts_windows_above_the_threshold(self):
        amplitude = np.array([[10.0], [20.0], [30.0], [40.0]])
        # threshold is 15% of CAL
        assert duty_cycle(amplitude)[0] == pytest.approx(75.0)

    def test_an_empty_session_is_nan_not_zero(self):
        assert np.isnan(duty_cycle(np.zeros((0, 9)))).all()


class TestGroupMean:
    def test_a_failed_channel_does_not_destroy_its_group(self):
        amplitude = np.array([[10.0, np.nan, 30.0]])
        assert group_mean(amplitude, (0, 1, 2))[0] == pytest.approx(20.0)

    def test_an_empty_group_is_a_programming_error(self):
        with pytest.raises(ValueError):
            group_mean(np.zeros((1, 9)), ())


class TestCorrectionRate:
    def test_correction_rate_is_a_percentage_of_windows(self):
        assert correction_rate(25, 100) == pytest.approx(25.0)

    def test_no_windows_is_zero_not_a_division_error(self):
        assert correction_rate(0, 0) == 0.0
