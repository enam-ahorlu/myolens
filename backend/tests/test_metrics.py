"""Metrics, and the null co-contraction case the plan names as a required test.

TODO(TD-06): these fixtures are hand-built rather than drawn from the demonstration recordings,
but the integration tests share fixtures with the shipped demo data, so a quirk of those three
held-out subjects could be encoded as an expectation rather than a requirement.
Prudent & inadvertent — using real held-out data was the cheapest way to get realistic
behaviour and the trade was accepted knowingly. Impact: Low.
Repayment: v1.1, synthetic fixtures generated at the boundary conditions.
"""

from __future__ import annotations

import math
from uuid import uuid4

import numpy as np
import pytest

from app.domain.bouts import Bout
from app.domain.metrics import (
    ACTIVITY_THRESHOLD,
    co_contraction_index,
    compute_task_metrics,
    correction_rate,
    duty_cycle,
    group_mean,
    percent_cal,
)
from app.domain.montage import GROUPS, MuscleGroup
from app.domain.windowing import window_time_ms

THRESHOLD_PCT = ACTIVITY_THRESHOLD * 100.0


def _bout(**overrides) -> Bout:
    defaults = dict(
        id=str(uuid4()),
        session_id="s1",
        task="WAK",
        start_window=0,
        end_window=10,
        start_ms=window_time_ms(0)[0],
        end_ms=window_time_ms(9)[1],
        window_count=10,
        mean_confidence=0.8,
        flagged=False,
        flag_reasons=(),
    )
    defaults.update(overrides)
    return Bout(**defaults)


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


class TestComputeTaskMetrics:
    """F1: the §3.3 metric set, assembled from a task's approved bouts and the session's
    per-window %CAL array. The five-window fixture below is hand-built so every field can be
    checked against an independently-computed expectation to 1e-6 (F1's acceptance criterion),
    using the already-unit-tested primitives directly on the known array rather than going
    through ``compute_task_metrics`` a second time.
    """

    AMPLITUDE = np.array(
        [
            # ch0  ch1  ch2  ch3  ch4  ch5  ch6  ch7  ch8
            [10.0, 50.0, 50.0, 20.0, 30.0, 30.0, 10.0, 10.0, 10.0],
            [10.0, 60.0, 40.0, 25.0, 35.0, 25.0, 15.0, 15.0, 15.0],
            [10.0, 20.0, 20.0, 80.0, 5.0, 5.0, 50.0, 50.0, 50.0],
            [10.0, 10.0, 10.0, 90.0, 5.0, 5.0, 60.0, 60.0, 60.0],
            [10.0, 5.0, 5.0, 95.0, 5.0, 5.0, 70.0, 70.0, 70.0],
        ]
    )

    def _bouts(self):
        first = _bout(
            task="WAK",
            start_window=0,
            end_window=2,
            start_ms=window_time_ms(0)[0],
            end_ms=window_time_ms(1)[1],
            window_count=2,
            mean_confidence=0.9,
            corrected=False,
        )
        second = _bout(
            task="WAK",
            start_window=2,
            end_window=5,
            start_ms=window_time_ms(2)[0],
            end_ms=window_time_ms(4)[1],
            window_count=3,
            mean_confidence=0.6,
            corrected=True,
        )
        return [first, second]

    def test_matches_an_independently_computed_fixture_to_1e_6(self):
        bouts = self._bouts()
        result = compute_task_metrics("WAK", bouts, self.AMPLITUDE)

        np.testing.assert_allclose(result.amp_mean, self.AMPLITUDE.mean(axis=0), atol=1e-6)
        np.testing.assert_allclose(result.amp_peak, self.AMPLITUDE.max(axis=0), atol=1e-6)
        np.testing.assert_allclose(result.duty_cycle, duty_cycle(self.AMPLITUDE), atol=1e-6)

        expected_knee = co_contraction_index(
            group_mean(self.AMPLITUDE, GROUPS[MuscleGroup.KNEE_EXTENSOR]),
            group_mean(self.AMPLITUDE, GROUPS[MuscleGroup.KNEE_FLEXOR]),
        )
        assert result.cci_knee.value == pytest.approx(expected_knee.value, abs=1e-6)
        assert result.cci_knee.windows_used == expected_knee.windows_used
        assert result.cci_knee.windows_total == expected_knee.windows_total

        expected_ankle = co_contraction_index(
            group_mean(self.AMPLITUDE, GROUPS[MuscleGroup.DORSIFLEXOR]),
            group_mean(self.AMPLITUDE, GROUPS[MuscleGroup.PLANTARFLEXOR]),
        )
        assert result.cci_ankle.value == pytest.approx(expected_ankle.value, abs=1e-6)

        # bout_count, duration, confidence and correction rate come from the bouts, not the
        # amplitude array -- checked against hand arithmetic independent of both.
        assert result.bout_count == 2
        expected_duration_s = (window_time_ms(1)[1] - window_time_ms(0)[0]) / 1000.0 + (
            window_time_ms(4)[1] - window_time_ms(2)[0]
        ) / 1000.0
        assert result.bout_duration_total_s == pytest.approx(expected_duration_s, abs=1e-6)
        assert result.model_confidence_mean == pytest.approx((0.9 * 2 + 0.6 * 3) / 5, abs=1e-6)
        assert result.correction_rate_pct == pytest.approx(60.0, abs=1e-6)  # 3 of 5 windows

    def test_reads_only_the_windows_its_bouts_cover(self):
        """A second task's windows sitting elsewhere in the same session's amplitude array must
        not leak into this task's metrics."""
        contaminated = self.AMPLITUDE.copy()
        contaminated[0] = 999.0  # outside both bouts below
        bouts = [
            _bout(
                task="STDUP",
                start_window=1,
                end_window=3,
                window_count=2,
                mean_confidence=0.7,
            )
        ]
        result = compute_task_metrics("STDUP", bouts, contaminated)
        np.testing.assert_allclose(result.amp_mean, contaminated[1:3].mean(axis=0), atol=1e-6)
        assert not np.any(result.amp_mean == pytest.approx(999.0))

    def test_a_dead_calibration_channel_propagates_as_nan_not_zero(self):
        amplitude = self.AMPLITUDE.copy()
        amplitude[:, 0] = np.nan  # e.g. a channel whose calibration peak was <= 0
        bouts = [_bout(task="WAK", start_window=0, end_window=5, window_count=5)]

        result = compute_task_metrics("WAK", bouts, amplitude)

        assert math.isnan(result.amp_mean[0])
        assert math.isnan(result.amp_peak[0])

    def test_no_bouts_is_a_programming_error(self):
        with pytest.raises(ValueError):
            compute_task_metrics("WAK", [], self.AMPLITUDE)
