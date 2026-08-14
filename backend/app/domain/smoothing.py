"""Temporal smoothing of per-window predictions (D6, a named contribution -- SRS §5.8.1, §5.13).

Two passes, in order: a five-window majority vote, then a per-class minimum dwell. The thesis
measures only window-level accuracy; smoothing bout *coherence* against that unsmoothed baseline
is new evidence this system produces, not something carried over from the thesis's own claims.

The frozen per-class dwell times come from D6 directly and must not be tuned per deployment --
they are a reported result, and changing them would invalidate the comparison the Testing Report
makes against the unsmoothed baseline.
"""

from __future__ import annotations

import itertools

import numpy as np

from app.domain.windowing import STEP_MS
from app.serving.predictor import CLASSES, N_CLASSES

MAJORITY_VOTE_WINDOW = 5

#: Minimum dwell time per task, in milliseconds (D6, frozen).
DWELL_MS: dict[str, float] = {
    "WAK": 1000.0,
    "UPS": 1200.0,
    "DNS": 1200.0,
    "STDUP": 800.0,
}


def min_dwell_windows(task: str) -> int:
    """The frozen dwell time expressed in windows, at this deployment's 125 ms hop.

    Rounds rather than floors or ceils: STEP_MS's own docstring (``windowing.py``) treats the
    window/step geometry as exact, and a systematic floor would silently shrink every dwell
    requirement by up to one whole window against the frozen millisecond figures.
    """
    return round(DWELL_MS[task] / STEP_MS)


def majority_vote_smooth(
    label_indices: np.ndarray, window: int = MAJORITY_VOTE_WINDOW
) -> np.ndarray:
    """A centred sliding-window majority vote over per-window class indices (into ``CLASSES``).

    Ties are broken in favour of the window's own centre label when the centre label is among
    the tied modes, and by class index otherwise. Breaking every tie by class index alone would
    make the smoothed sequence depend on ``CLASSES``' arbitrary ordering rather than on what the
    window itself predicted; preferring the centre label when it is a legitimate tied winner
    keeps the vote from nudging a genuinely ambiguous window toward whichever class happens to
    sort first.
    """
    if label_indices.ndim != 1:
        raise ValueError(f"expected a 1-D array of class indices, got shape {label_indices.shape}")
    n = label_indices.shape[0]
    if n == 0:
        return label_indices.copy()

    half = window // 2
    smoothed = np.empty_like(label_indices)
    for i in range(n):
        start = max(0, i - half)
        end = min(n, i + half + 1)
        counts = np.bincount(label_indices[start:end], minlength=N_CLASSES)
        top = int(counts.max())
        tied = np.flatnonzero(counts == top)
        centre = label_indices[i]
        smoothed[i] = centre if centre in tied else int(tied[0])
    return smoothed


def enforce_minimum_dwell(label_indices: np.ndarray) -> np.ndarray:
    """Absorb any run shorter than its class's minimum dwell into a neighbouring run.

    Repeated to a fixed point: merging a short run can lengthen (or shorten, at its far edge) an
    adjacent run, which can in turn create or resolve a violation elsewhere, so a single pass is
    not sufficient. Bounded by ``len(label_indices)`` passes, which is always enough -- each pass
    that makes any change strictly reduces the number of distinct runs, and there cannot be more
    runs than windows.
    """
    if label_indices.ndim != 1:
        raise ValueError(f"expected a 1-D array of class indices, got shape {label_indices.shape}")
    labels = label_indices.copy()
    n = labels.shape[0]
    if n == 0:
        return labels

    for _ in range(n):
        runs = _run_lengths(labels)
        changed = False
        for start, end, class_idx in runs:
            length = end - start
            if length >= min_dwell_windows(CLASSES[class_idx]):
                continue
            # Merge into whichever neighbour is longer (ties favour the previous run, so a
            # short leading run merges forward rather than leaving a still-short run behind it).
            prev_run = next((r for r in runs if r[1] == start), None)
            next_run = next((r for r in runs if r[0] == end), None)
            if prev_run is None and next_run is None:
                continue  # the whole recording is one short run; nothing to merge into
            prev_len = (prev_run[1] - prev_run[0]) if prev_run else -1
            next_len = (next_run[1] - next_run[0]) if next_run else -1
            target = prev_run[2] if prev_len >= next_len else next_run[2]
            labels[start:end] = target
            changed = True
        if not changed:
            break
    return labels


def _run_lengths(labels: np.ndarray) -> list[tuple[int, int, int]]:
    """``[(start, end, class_index), ...]`` half-open run boundaries."""
    if labels.shape[0] == 0:
        return []
    change_points = np.flatnonzero(labels[1:] != labels[:-1]) + 1
    boundaries = [0, *change_points.tolist(), labels.shape[0]]
    return [(s, e, int(labels[s])) for s, e in itertools.pairwise(boundaries)]
