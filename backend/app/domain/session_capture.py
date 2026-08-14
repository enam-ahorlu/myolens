"""Parsing an uploaded session recording (D2/D3, SRS §4.2 D).

Simpler than ``calibration_capture``'s parser: a session upload carries no ``label`` column and
is treated as a single continuous recording, never split into blocks. That distinction matters
for ``app.domain.signal.bandpass_filter`` -- a zero-phase filter that must run over one
uninterrupted recording (D4), not per-block the way a calibration capture's contiguous task runs
are, because there is no task boundary here to protect the filter's edges from.
"""

from __future__ import annotations

import gzip
import io

import numpy as np
import pandas as pd

from app.domain.montage import MONTAGE, validate_montage
from app.domain.windowing import MAX_SESSION_SECONDS, SAMPLING_RATE_HZ, exceeds_duration_cap
from app.errors import MontageRejected, SessionTooLong

TIME_COLUMN = "Time"


def _read_frame(raw_bytes: bytes) -> pd.DataFrame:
    """CSV, or gzipped CSV (D2) -- gzip's magic bytes (``\\x1f\\x8b``) distinguish the two
    without relying on the object name, which a signed-URL upload never validates anyway."""
    if raw_bytes[:2] == b"\x1f\x8b":
        raw_bytes = gzip.decompress(raw_bytes)
    try:
        return pd.read_csv(io.BytesIO(raw_bytes))
    except Exception as exc:
        raise MontageRejected([{"reason": "unparseable_csv", "detail": str(exc)}]) from exc


def parse_session_csv(raw_bytes: bytes) -> np.ndarray:
    """Parse an uploaded session recording into a ``(n_samples, 9)`` montage-ordered signal.

    Raises :class:`MontageRejected` (409, D3) for a channel mismatch, and
    :class:`SessionTooLong` (413, D2) for a recording beyond the ten-minute cap -- both upload
    defects a clinician can fix by re-exporting or splitting the recording, not programming
    errors.
    """
    frame = _read_frame(raw_bytes)

    channel_columns = [c for c in frame.columns if c != TIME_COLUMN]
    violations = validate_montage(channel_columns)
    if violations:
        raise MontageRejected([v.as_dict() for v in violations])

    signal = frame[list(MONTAGE)].to_numpy(dtype=np.float64)

    if exceeds_duration_cap(signal.shape[0]):
        raise SessionTooLong(signal.shape[0] / SAMPLING_RATE_HZ, MAX_SESSION_SECONDS)

    return signal
