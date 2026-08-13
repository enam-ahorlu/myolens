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

from dataclasses import dataclass

import numpy as np

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
