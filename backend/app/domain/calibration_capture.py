"""Turning an uploaded, labelled calibration CSV into calibration sufficiency, a %CAL
reference and an out-of-distribution distance (C1-C4, SRS §4.2 C).

The upload format matches the shipped demo captures exactly: ``Time`` + the nine montage
channels, in the exact column names ``app.domain.montage`` enforces, plus a ``label`` column
holding one of the four frozen task codes for every sample. A calibration capture typically
contains several contiguous blocks per task (C2's "≥3 non-contiguous blocks"), so a label
change in the CSV marks a block boundary.

**Filtering happens per block, never across one.** ``app.domain.signal.bandpass_filter`` is a
zero-phase filter over a *continuous* recording; splicing two separately-recorded blocks
together first and filtering the splice would smear a discontinuity into both blocks' first
and last few dozen milliseconds. Each contiguous same-label run is therefore treated as its
own short trial: filtered, enveloped and windowed independently, then the resulting windows
from every block are pooled per task for sufficiency counting.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from app.config import get_settings
from app.domain.csv_upload import read_upload_frame
from app.domain.features import extract_freq72
from app.domain.montage import MONTAGE, validate_montage
from app.domain.normalisation import zscore_features
from app.domain.signal import bandpass_filter, linear_envelope
from app.domain.windowing import WINDOW_SAMPLES, sliding_windows
from app.errors import MontageRejected

LABEL_COLUMN = "label"


@dataclass(frozen=True)
class TaskBlock:
    """One contiguous, single-task run of raw samples from the upload."""

    task: str
    signal: np.ndarray  # (n_samples, 9), montage-ordered


@dataclass(frozen=True)
class CalibrationCapture:
    """Everything downstream of parsing needs, aggregated across every block in the upload."""

    #: task -> (window_count, block_count that produced at least one window)
    counts: dict[str, tuple[int, int]]
    #: Pooled per-window Freq-72 features, from every task and block, raw bandpassed windows.
    features: np.ndarray  # (n_windows_total, 72)
    #: Pooled per-window envelope peak (max over the window), for the %CAL reference.
    envelope_peaks: np.ndarray  # (n_windows_total, 9)


def parse_calibration_csv(csv_bytes: bytes) -> list[TaskBlock]:
    """Parse an uploaded calibration CSV into contiguous per-task blocks.

    Raises :class:`MontageRejected` if the channel columns don't match the frozen montage, or
    if no ``label`` column is present -- both are upload defects a clinician can fix, not
    programming errors, so they surface as the same 409 the session-upload path uses.
    """
    frame = read_upload_frame(csv_bytes, get_settings().max_upload_bytes)

    # The upload also carries a leading `Time` column and a trailing `label` column (see the
    # module docstring); the montage contract itself only governs the nine channel columns
    # between them, so those two are excluded before handing the rest to validate_montage --
    # otherwise every legitimate calibration upload would fail on "11 channels, expected 9".
    channel_columns = [c for c in frame.columns if c != LABEL_COLUMN and c != "Time"]
    violations: list[object] = list(validate_montage(channel_columns))
    if LABEL_COLUMN not in frame.columns:
        violations.append({"reason": "missing_label_column", "expected": LABEL_COLUMN})
    if violations:
        raise MontageRejected([v.as_dict() if hasattr(v, "as_dict") else v for v in violations])

    labels = frame[LABEL_COLUMN].astype(str).to_numpy()
    signal = frame[list(MONTAGE)].to_numpy(dtype=np.float64)

    # A new block starts wherever the label differs from the previous row.
    change_points = np.flatnonzero(labels[1:] != labels[:-1]) + 1
    boundaries = [0, *change_points.tolist(), len(labels)]

    blocks: list[TaskBlock] = []
    for start, end in itertools.pairwise(boundaries):
        blocks.append(TaskBlock(task=str(labels[start]), signal=signal[start:end]))
    return blocks


def analyse_capture(blocks: list[TaskBlock]) -> CalibrationCapture:
    """Filter, envelope, window and feature-extract every block, then pool the results."""
    counts: dict[str, list[int]] = {}
    feature_chunks: list[np.ndarray] = []
    peak_chunks: list[np.ndarray] = []

    for block in blocks:
        if block.signal.shape[0] < WINDOW_SAMPLES:
            continue  # too short to yield even one window; does not count as a block either

        filtered = bandpass_filter(block.signal)
        envelope = linear_envelope(filtered)
        raw_windows = sliding_windows(filtered)  # (n_windows, WINDOW_SAMPLES, 9)
        env_windows = sliding_windows(envelope)

        n_windows = raw_windows.shape[0]
        if n_windows == 0:
            continue

        window_count, block_count = counts.get(block.task, [0, 0])
        counts[block.task] = [window_count + n_windows, block_count + 1]

        feature_chunks.append(extract_freq72(np.ascontiguousarray(raw_windows)))
        peak_chunks.append(np.ascontiguousarray(env_windows).max(axis=1))  # (n_windows, 9)

    if feature_chunks:
        features = np.concatenate(feature_chunks, axis=0)
        envelope_peaks = np.concatenate(peak_chunks, axis=0)
    else:
        features = np.empty((0, 72))
        envelope_peaks = np.empty((0, 9))

    return CalibrationCapture(
        counts={task: (wc, bc) for task, (wc, bc) in counts.items()},
        features=features,
        envelope_peaks=envelope_peaks,
    )


def session_zscored_features(capture: CalibrationCapture) -> np.ndarray:
    """The transductive normalisation (ADR-003) applied to this capture's own pooled windows,
    for the OOD check -- never against another session's or participant's statistics."""
    if capture.features.shape[0] == 0:
        return capture.features
    return zscore_features(capture.features)
