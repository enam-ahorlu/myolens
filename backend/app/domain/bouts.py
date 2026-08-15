"""Bout construction, review flagging, and correction (D7, D8, E3-E6;
schema ``sessions/{sid}/bouts/{bid}``).

A bout is the unit the reviewer works with (SRS §2 glossary): a contiguous run of windows
carrying the same task label *after* smoothing (``app.domain.smoothing``). Flagging happens here,
against the already-smoothed, already-output-space-restricted probabilities, because D8's
thresholds are about how a human should spend their attention on the model's *final* proposal,
not on the noisier pre-smoothing per-window signal.

The correction operations below (relabel, split, merge, exclude) work only from a bout's stored
aggregates -- ``mean_confidence`` and ``flag_reasons`` -- because the per-window probability
matrix a bout was built from is not itself persisted (only the bouts derived from it are). Split
and merge therefore carry those aggregates forward approximately rather than recomputing them
exactly; each function's docstring says so at the point it matters.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from uuid import uuid4

import numpy as np

from app.domain.windowing import window_time_ms
from app.serving.predictor import CLASSES


class ExclusionReason(StrEnum):
    """E6's three named reasons a bout is excluded from metrics but kept in the record."""

    ARTEFACT = "artefact"
    TRANSITION = "transition"
    UNOBSERVED = "unobserved"


@dataclass(frozen=True)
class Bout:
    id: str
    session_id: str
    task: str
    start_window: int
    end_window: int  # exclusive
    start_ms: float
    end_ms: float
    window_count: int
    mean_confidence: float
    flagged: bool
    flag_reasons: tuple[str, ...]
    excluded: bool = False
    exclusion_reason: str | None = None
    #: E8/F4: has an operator changed this bout since automatic segmentation produced it.
    #: ``original_task`` is set once, on the *first* correction, and never overwritten again --
    #: it must answer "what did the model originally say", not "what did the last edit start
    #: from", or a chain of corrections would silently erase the model's own proposal.
    corrected: bool = False
    original_task: str | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "task": self.task,
            "startWindow": self.start_window,
            "endWindow": self.end_window,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "windowCount": self.window_count,
            "meanConfidence": self.mean_confidence,
            "flagged": self.flagged,
            "flagReasons": list(self.flag_reasons),
            "excluded": self.excluded,
            "exclusionReason": self.exclusion_reason,
            "corrected": self.corrected,
            "originalTask": self.original_task,
        }

    @staticmethod
    def from_document(doc: dict[str, Any]) -> Bout:
        return Bout(
            id=doc["id"],
            session_id=doc["sessionId"],
            task=doc["task"],
            start_window=doc["startWindow"],
            end_window=doc["endWindow"],
            start_ms=doc["startMs"],
            end_ms=doc["endMs"],
            window_count=doc["windowCount"],
            mean_confidence=doc["meanConfidence"],
            flagged=doc["flagged"],
            flag_reasons=tuple(doc["flagReasons"]),
            excluded=doc.get("excluded", False),
            exclusion_reason=doc.get("exclusionReason"),
            corrected=doc.get("corrected", False),
            original_task=doc.get("originalTask"),
        )


def build_bouts(
    session_id: str,
    label_indices: np.ndarray,
    probabilities: np.ndarray,
    *,
    dns_wak_margin: float,
    low_confidence_threshold: float,
) -> list[Bout]:
    """Merge adjacent same-label windows into bouts (D7), and flag each one (D8).

    ``probabilities`` must already be the output-space-restricted, per-window probabilities the
    smoothed ``label_indices`` were derived from -- confidence and the DNS/WAK margin are read
    from them directly, not recomputed from a raw ensemble output.
    """
    if label_indices.shape[0] != probabilities.shape[0]:
        raise ValueError(
            f"labels and probabilities describe different numbers of windows: "
            f"{label_indices.shape[0]} != {probabilities.shape[0]}"
        )
    n = label_indices.shape[0]
    if n == 0:
        return []

    dns_index = CLASSES.index("DNS")
    wak_index = CLASSES.index("WAK")

    change_points = np.flatnonzero(label_indices[1:] != label_indices[:-1]) + 1
    boundaries = [0, *change_points.tolist(), n]

    bouts: list[Bout] = []
    for start, end in itertools.pairwise(boundaries):
        task = CLASSES[int(label_indices[start])]
        window_probs = probabilities[start:end]
        winning = window_probs[np.arange(end - start), label_indices[start:end]]
        mean_confidence = float(winning.mean())
        margin = float(abs(window_probs[:, dns_index].mean() - window_probs[:, wak_index].mean()))

        reasons: list[str] = []
        if mean_confidence < low_confidence_threshold:
            reasons.append("low_confidence")
        if margin < dns_wak_margin:
            reasons.append("dns_wak_margin")

        start_ms, _ = window_time_ms(start)
        _, end_ms = window_time_ms(end - 1)

        bouts.append(
            Bout(
                id=str(uuid4()),
                session_id=session_id,
                task=task,
                start_window=start,
                end_window=end,
                start_ms=start_ms,
                end_ms=end_ms,
                window_count=end - start,
                mean_confidence=mean_confidence,
                flagged=bool(reasons),
                flag_reasons=tuple(reasons),
            )
        )
    return bouts


def relabel_bout(bout: Bout, new_task: str) -> Bout:
    """E3: relabel a bout to any calibrated task. Calibrated-task validation is the caller's
    responsibility (``routers/sessions.py`` checks it against the session's active calibration)
    -- this function only knows how to apply a task change, not what tasks are legal here.
    """
    if new_task not in CLASSES:
        raise ValueError(f"'{new_task}' is not one of {CLASSES}")
    if new_task == bout.task:
        return bout  # not a correction; nothing to record
    return replace(
        bout,
        task=new_task,
        corrected=True,
        original_task=bout.original_task or bout.task,
    )


def exclude_bout(bout: Bout, reason: ExclusionReason) -> Bout:
    """E6: exclude a bout from metrics without deleting it -- the record is retained, the
    exclusion (and its reason) is what F1's metric computation checks."""
    return replace(bout, excluded=True, exclusion_reason=reason.value)


def split_bout(bout: Bout, at_window: int) -> tuple[Bout, Bout]:
    """E4: split a bout into two at a window boundary. ``at_window`` is the absolute window
    index the *second* bout starts at, and must fall strictly inside the bout so neither half
    is empty (D7's "no window lost" acceptance).

    The per-window probabilities the parent bout's ``mean_confidence``/``flag_reasons`` were
    computed from are not persisted, so both halves inherit them unchanged from the parent
    rather than being recomputed -- an approximation, stated here rather than left implicit.
    """
    if not (bout.start_window < at_window < bout.end_window):
        raise ValueError(
            f"split point {at_window} must fall strictly inside "
            f"[{bout.start_window}, {bout.end_window})"
        )
    _start_ms, _ = window_time_ms(bout.start_window)
    split_start_ms, _ = window_time_ms(at_window)
    _, first_end_ms = window_time_ms(at_window - 1)
    _, end_ms = window_time_ms(bout.end_window - 1)

    first = replace(
        bout,
        end_window=at_window,
        end_ms=first_end_ms,
        window_count=at_window - bout.start_window,
    )
    second = replace(
        bout,
        id=str(uuid4()),
        start_window=at_window,
        start_ms=split_start_ms,
        end_ms=end_ms,
        window_count=bout.end_window - at_window,
    )
    return first, second


def merge_bouts(earlier: Bout, later: Bout) -> Bout:
    """E5: merge a bout with an adjacent same-label neighbour. ``earlier``/``later`` must be
    ordered by window index already; the caller (``routers/sessions.py``) determines that order
    from the two bouts' own ``start_window`` before calling this.

    Confidence is carried forward as a window-count-weighted average of the two bouts', which is
    exact only if their underlying per-window confidences were uniform -- again an approximation
    for the reason ``split_bout`` documents. Flags are the *union* of both bouts' reasons rather
    than being recomputed: a flag should not silently disappear because its bout was merged into
    a cleaner-looking neighbour.
    """
    if earlier.session_id != later.session_id:
        raise ValueError("bouts belong to different sessions")
    if earlier.task != later.task:
        raise ValueError(
            f"merge requires the same task on both sides, got '{earlier.task}' and '{later.task}'"
        )
    if earlier.end_window != later.start_window:
        raise ValueError(f"bouts are not adjacent: {earlier.end_window} != {later.start_window}")

    total_windows = earlier.window_count + later.window_count
    weighted_confidence = (
        earlier.mean_confidence * earlier.window_count + later.mean_confidence * later.window_count
    ) / total_windows
    reasons = tuple(dict.fromkeys((*earlier.flag_reasons, *later.flag_reasons)))

    return replace(
        earlier,
        end_window=later.end_window,
        end_ms=later.end_ms,
        window_count=total_windows,
        mean_confidence=weighted_confidence,
        flagged=bool(reasons),
        flag_reasons=reasons,
        corrected=earlier.corrected or later.corrected,
        original_task=earlier.original_task or later.original_task,
    )
