"""Bout construction and review flagging (D7, D8; schema ``sessions/{sid}/bouts/{bid}``).

A bout is the unit the reviewer works with (SRS §2 glossary): a contiguous run of windows
carrying the same task label *after* smoothing (``app.domain.smoothing``). Flagging happens here,
against the already-smoothed, already-output-space-restricted probabilities, because D8's
thresholds are about how a human should spend their attention on the model's *final* proposal,
not on the noisier pre-smoothing per-window signal.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import numpy as np

from app.domain.windowing import window_time_ms
from app.serving.predictor import CLASSES


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
