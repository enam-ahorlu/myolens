"""Calibration sufficiency, the %CAL reference, and the out-of-distribution guard.

Calibration does two jobs that are usually kept apart, and it is worth being explicit that both
are load-bearing:

* it supplies the per-channel amplitude reference every later metric is expressed against, and
* it is the only opportunity to check that this participant resembles the population the model
  was trained on, before any prediction is made about them.

Sufficiency is tracked **per task**, not per participant. Many rehabilitation participants cannot
safely descend stairs. Excluding an uncalibrated task from the output space entirely is honest;
predicting it and then filtering the result is not, because the classifier's probability mass has
already been distributed over a class the participant never performed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.serving.predictor import CLASSES


@dataclass(frozen=True)
class TaskCalibration:
    """Whether one task has enough labelled data to be predicted for this participant."""

    task: str
    window_count: int
    block_count: int
    min_windows: int
    min_blocks: int

    @property
    def sufficient(self) -> bool:
        return self.window_count >= self.min_windows and self.block_count >= self.min_blocks

    @property
    def status(self) -> str:
        if self.window_count == 0:
            return "not_attempted"
        return "calibrated" if self.sufficient else "insufficient"


def assess(
    counts: dict[str, tuple[int, int]], min_windows: int, min_blocks: int
) -> dict[str, TaskCalibration]:
    """Assess every class, including those with no data at all.

    Tasks absent from ``counts`` are reported as not attempted rather than omitted. An absent
    task and an unmentioned task look identical in a dictionary and are completely different
    clinically, so the output space is always the full class list.
    """
    result: dict[str, TaskCalibration] = {}
    for task in CLASSES:
        window_count, block_count = counts.get(task, (0, 0))
        result[task] = TaskCalibration(
            task=task,
            window_count=window_count,
            block_count=block_count,
            min_windows=min_windows,
            min_blocks=min_blocks,
        )
    return result


def calibrated_tasks(assessment: dict[str, TaskCalibration]) -> tuple[str, ...]:
    """The output space: only tasks this participant is calibrated for."""
    return tuple(task for task, cal in assessment.items() if cal.sufficient)


def restrict_to_calibrated(probabilities: np.ndarray, calibrated: tuple[str, ...]) -> np.ndarray:
    """Zero every uncalibrated class and renormalise (D5): an uncalibrated task must never be
    the argmax of a restricted row, because it was never a legitimate candidate for this
    participant in the first place -- there is no evidence the model's usual accuracy holds for
    a movement it never saw calibrated.

    Raises rather than silently returning an all-zero row if ``calibrated`` is empty; the caller
    (``routers/sessions.py``) is expected to have already refused segmentation via
    ``NotCalibrated`` before reaching this point.
    """
    if not calibrated:
        raise ValueError("cannot restrict to an empty calibrated-task set")
    if probabilities.ndim != 2 or probabilities.shape[1] != len(CLASSES):
        raise ValueError(
            f"expected (n_windows, {len(CLASSES)}) probabilities, got shape {probabilities.shape}"
        )
    mask = np.array([1.0 if task in calibrated else 0.0 for task in CLASSES])
    masked = probabilities * mask
    row_sums = masked.sum(axis=1, keepdims=True)
    safe_sums = np.where(row_sums > 0.0, row_sums, 1.0)
    return masked / safe_sums


def envelope_peak(envelope: np.ndarray) -> np.ndarray:
    """Per-channel peak of the calibration envelope — the %CAL reference vector.

    Uses the 99th percentile rather than the maximum. A single-sample artefact — a cable knock,
    a movement transient — would otherwise become the denominator for every amplitude in the
    session, deflating every subsequent figure by an arbitrary factor that nothing in the output
    would reveal.
    """
    if envelope.ndim != 2:
        raise ValueError(f"expected (n_windows, n_channels), got shape {envelope.shape}")
    if envelope.shape[0] == 0:
        raise ValueError("cannot derive a %CAL reference from an empty calibration capture")
    return np.percentile(envelope, 99.0, axis=0)


def mahalanobis_distance(
    features: np.ndarray, mean: np.ndarray, inverse_covariance: np.ndarray
) -> float:
    """Mean Mahalanobis distance of a calibration capture from the training distribution.

    The mean over windows rather than the maximum: a handful of unusual windows is normal in any
    real recording, and thresholding on the worst one would refuse almost everybody.
    """
    if features.ndim != 2:
        raise ValueError(f"expected (n_windows, n_features), got shape {features.shape}")
    centred = features - mean
    squared = np.einsum("ij,jk,ik->i", centred, inverse_covariance, centred)
    return float(np.sqrt(np.maximum(squared, 0.0)).mean())


def difficulty_band(distance: float, threshold: float) -> str:
    """Predicted-difficulty band from the OOD distance.

    The thesis found a ~29 percentage-point spread in per-subject accuracy and a 0.74-0.83
    cross-model correlation in which subjects were hard, but could not say in advance which ones
    those would be. The distance is already computed for the refusal guard, so banding it is
    nearly free, and storing the band alongside the realised correction rate turns ordinary use
    into evidence about whether subject difficulty is predictable at all.

    Presented as review priority, never as a prediction of accuracy for this participant.
    """
    if distance < threshold * 0.5:
        return "typical"
    if distance < threshold * 0.8:
        return "moderate"
    return "atypical"


# TODO(TD-04): calibration statistics are recomputed on every request rather than cached.
# Prudent & deliberate. A cache needs an invalidation rule, and the correct key involves both the
# participant and the calibration version, which supersede rather than overwrite — designing that
# properly was not affordable inside the window and designing it badly would serve a stale %CAL
# reference, which is worse than being slow.
# Impact: ~40 ms per assessment. Priority: Medium.
# Repayment: v1.1, cache keyed on (participant_id, calibration_version), invalidated on write.
