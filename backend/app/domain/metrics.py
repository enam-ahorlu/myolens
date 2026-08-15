"""Task-conditioned metrics, computed only on an approved segmentation.

Every amplitude here is expressed in ``%CAL`` — a percentage of the participant's own peak
calibration envelope, per channel, from the same session. It is **not** %MVC. Maximal voluntary
contraction testing is contraindicated in the populations this tool is aimed at, so there is no
MVC anchor to normalise against. The consequence is stated everywhere it matters: amplitudes are
comparable within a session and meaningless across sessions.

That limitation is also why the co-contraction indices lead and raw amplitude is secondary. A CCI
is a *ratio* of two simultaneous amplitudes, so the missing anchor cancels: if both groups are
scaled by the same unknown factor, the ratio is unchanged. Raw amplitude carries the anchor's
absence directly. Reporting them in that order is a deliberate ordering, not a layout choice.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from app.domain.montage import GROUPS, MuscleGroup

if TYPE_CHECKING:
    from app.domain.bouts import Bout

#: A channel is considered active when its envelope exceeds this fraction of its own
#: calibration peak. Below it, the signal is not distinguishable from resting activity plus
#: noise, and treating it as a real contraction inflates every ratio it participates in.
ACTIVITY_THRESHOLD: float = 0.15


@dataclass(frozen=True)
class CoContractionResult:
    """A co-contraction index, or an explicit statement that none is defined."""

    value: float | None
    windows_used: int
    windows_total: int

    @property
    def is_null(self) -> bool:
        return self.value is None


def percent_cal(envelope: np.ndarray, calibration_peak: np.ndarray) -> np.ndarray:
    """Express an envelope as a percentage of the participant's calibration peak.

    ``envelope`` is ``(n_windows, n_channels)``; ``calibration_peak`` is ``(n_channels,)``.

    A zero or negative calibration peak means that channel produced no usable calibration signal
    — a disconnected or failed electrode. Dividing by it would yield infinity, which would then
    propagate silently through every downstream mean. Such channels yield NaN instead, which
    propagates loudly and is filtered explicitly wherever it matters.
    """
    if envelope.ndim != 2:
        raise ValueError(f"expected (n_windows, n_channels), got shape {envelope.shape}")
    if calibration_peak.shape != (envelope.shape[1],):
        raise ValueError(
            f"calibration peak shape {calibration_peak.shape} does not match "
            f"{envelope.shape[1]} channels"
        )

    peak = np.asarray(calibration_peak, dtype=np.float64)
    safe_peak = np.where(peak > 0.0, peak, np.nan)
    return envelope / safe_peak * 100.0


def duty_cycle(amplitude_pct_cal: np.ndarray) -> np.ndarray:
    """Fraction of windows in which each channel exceeds the activity threshold, as a percentage."""
    if amplitude_pct_cal.shape[0] == 0:
        return np.full(amplitude_pct_cal.shape[1], np.nan)
    active = amplitude_pct_cal > (ACTIVITY_THRESHOLD * 100.0)
    return active.mean(axis=0) * 100.0


def co_contraction_index(
    agonist: np.ndarray,
    antagonist: np.ndarray,
    threshold_pct: float = ACTIVITY_THRESHOLD * 100.0,
) -> CoContractionResult:
    """Falconer & Winter co-contraction index over a set of windows.

    For each window *i*, with ``A_i`` the mean %CAL envelope of the agonist group and ``B_i``
    that of the antagonist group::

        CCI = mean over windows( 2 * min(A_i, B_i) / (A_i + B_i) ) * 100

    A window contributes only when **at least one** group is above the activity threshold. Where
    both groups are below it, the limb is at rest: the ratio is still arithmetically defined and
    is dominated entirely by the relative size of two noise floors, so including it would report
    the noise as co-contraction. Those windows are excluded, and the count that survived is
    returned alongside the value so the exclusion is visible rather than silent.

    When **no** window qualifies, the result is null — not zero. Zero co-contraction is a
    finding ("the antagonist was silent while the agonist worked"); no data is not a finding, and
    conflating them would let an empty recording read as a clinically interesting one. This edge
    case is a named unit test.
    """
    agonist = np.asarray(agonist, dtype=np.float64)
    antagonist = np.asarray(antagonist, dtype=np.float64)

    if agonist.shape != antagonist.shape:
        raise ValueError(
            f"agonist shape {agonist.shape} does not match antagonist {antagonist.shape}"
        )
    if agonist.ndim != 1:
        raise ValueError(f"expected one value per window, got shape {agonist.shape}")

    total = int(agonist.shape[0])
    if total == 0:
        return CoContractionResult(value=None, windows_used=0, windows_total=0)

    finite = np.isfinite(agonist) & np.isfinite(antagonist)
    active = (agonist > threshold_pct) | (antagonist > threshold_pct)
    usable = finite & active

    if not usable.any():
        return CoContractionResult(value=None, windows_used=0, windows_total=total)

    a = agonist[usable]
    b = antagonist[usable]
    denominator = a + b

    # Both groups above threshold implies a positive sum, but guard anyway: a NaN escaping into
    # a reported clinical metric is worse than an assertion here.
    if np.any(denominator <= 0.0):
        raise ValueError("non-positive amplitude sum in a window that passed the activity gate")

    per_window = 2.0 * np.minimum(a, b) / denominator
    return CoContractionResult(
        value=float(per_window.mean() * 100.0),
        windows_used=int(usable.sum()),
        windows_total=total,
    )


def group_mean(amplitude_pct_cal: np.ndarray, channels: tuple[int, ...]) -> np.ndarray:
    """Mean %CAL across a muscle group, per window, ignoring failed channels."""
    if not channels:
        raise ValueError("a muscle group must contain at least one channel")
    selected = amplitude_pct_cal[:, list(channels)]
    with np.errstate(invalid="ignore"):
        return np.nanmean(selected, axis=1)


def correction_rate(corrected_windows: int, total_windows: int) -> float:
    """Share of windows whose label the operator changed, as a percentage.

    The most interesting number the system produces: a per-session measure of operator
    disagreement with the model, and exactly the telemetry a maintenance plan needs in order to
    notice the model degrading against a population that has drifted away from the training set.
    """
    if total_windows <= 0:
        return 0.0
    return corrected_windows / total_windows * 100.0


@dataclass(frozen=True)
class TaskMetrics:
    """The §3.3 metric set (F1/F2/F4), for one task in one session's approved segmentation."""

    task: str
    bout_count: int
    bout_duration_total_s: float
    amp_mean: tuple[float, ...]  # 9 values, %CAL, montage order
    amp_peak: tuple[float, ...]
    duty_cycle: tuple[float, ...]
    cci_knee: CoContractionResult
    cci_ankle: CoContractionResult
    #: Mean ensemble confidence, pre-correction (F4) -- a bout's ``mean_confidence`` is never
    #: touched by ``relabel_bout``, so this reflects what the model actually reported even when
    #: the bout is now grouped under the task the operator corrected it *to*.
    model_confidence_mean: float
    correction_rate_pct: float


def compute_task_metrics(
    task: str, bouts: list[Bout], amplitude_pct_cal: np.ndarray
) -> TaskMetrics:
    """Aggregate the §3.3 metric set for one task from its approved (non-excluded) bouts.

    ``bouts`` must already be filtered to this task and to ``excluded=False`` -- this function
    does not re-check either, since the caller (``routers.sessions``) is the one grouping bouts
    by task in the first place and doing it twice would just be two places that could disagree.
    ``amplitude_pct_cal`` is the *whole session's* per-window, per-channel %CAL array; only the
    rows this task's bouts cover are read from it.
    """
    if not bouts:
        raise ValueError(f"no approved bouts for task '{task}'")

    window_indices = np.concatenate([np.arange(b.start_window, b.end_window) for b in bouts])
    task_amplitude = amplitude_pct_cal[window_indices]

    knee_extensor = group_mean(task_amplitude, GROUPS[MuscleGroup.KNEE_EXTENSOR])
    knee_flexor = group_mean(task_amplitude, GROUPS[MuscleGroup.KNEE_FLEXOR])
    dorsiflexor = group_mean(task_amplitude, GROUPS[MuscleGroup.DORSIFLEXOR])
    plantarflexor = group_mean(task_amplitude, GROUPS[MuscleGroup.PLANTARFLEXOR])

    total_windows = sum(b.window_count for b in bouts)
    corrected_windows = sum(b.window_count for b in bouts if b.corrected)
    confidence_mean = sum(b.mean_confidence * b.window_count for b in bouts) / total_windows
    duration_total_s = sum((b.end_ms - b.start_ms) for b in bouts) / 1000.0

    # A dead calibration channel (peak <= 0) makes percent_cal produce an all-NaN column; the
    # mean/max of an all-NaN slice is itself NaN, and numpy warns loudly about it every time.
    # The NaN propagating out is correct -- "no usable calibration signal" should read as
    # missing, not as a silent zero -- the warning about how it got there is not useful here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        amp_mean = np.nanmean(task_amplitude, axis=0)
        amp_peak = np.nanmax(task_amplitude, axis=0)

    return TaskMetrics(
        task=task,
        bout_count=len(bouts),
        bout_duration_total_s=duration_total_s,
        amp_mean=tuple(float(v) for v in amp_mean),
        amp_peak=tuple(float(v) for v in amp_peak),
        duty_cycle=tuple(float(v) for v in duty_cycle(task_amplitude)),
        cci_knee=co_contraction_index(knee_extensor, knee_flexor),
        cci_ankle=co_contraction_index(dorsiflexor, plantarflexor),
        model_confidence_mean=confidence_mean,
        correction_rate_pct=correction_rate(corrected_windows, total_windows),
    )
