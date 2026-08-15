"""NFR-01: a 10-minute session shall process in <=30s (SRS §4.1, §5).

This exercises the exact pipeline ``routers/sessions.py::segment_session`` runs -- window ->
Freq-72 / envelope -> whole-session z-score -> real ONNX ensemble -> restrict to calibrated ->
smooth -> build bouts -- against a synthetic recording at the documented 10-minute cap (D2), so
the number this test asserts is the one a clinician would actually wait on, not a proxy for it.

The real ONNX artefacts are required (unlike most of this suite, which fakes the ensemble out):
a fake predictor would make this a test of Python loop overhead, not of NFR-01's actual budget,
most of which is spent inside the two ONNX graphs.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from app.domain.bouts import build_bouts
from app.domain.calibration import restrict_to_calibrated
from app.domain.features import extract_freq72
from app.domain.montage import MONTAGE
from app.domain.normalisation import zscore_envelopes, zscore_features
from app.domain.signal import bandpass_filter, linear_envelope
from app.domain.smoothing import enforce_minimum_dwell, majority_vote_smooth
from app.domain.windowing import SAMPLING_RATE_HZ, sliding_windows
from app.serving.onnx_predictor import CLASSES, load_ensemble

ARTEFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts"

pytestmark = pytest.mark.skipif(
    not (ARTEFACT_DIR / "svm_freq72.onnx").exists(),
    reason="ONNX artefacts not present (expected under backend/artifacts/)",
)

#: NFR-01, verbatim.
BUDGET_SECONDS = 30.0
#: D2's hard cap -- the longest session this pipeline is ever asked to process in one call.
SESSION_SECONDS = 600


def _ten_minute_recording() -> np.ndarray:
    rng = np.random.default_rng(20260815)
    n_samples = int(SESSION_SECONDS * SAMPLING_RATE_HZ)
    return rng.normal(loc=0.0, scale=50.0, size=(n_samples, len(MONTAGE)))


def test_a_ten_minute_session_processes_within_the_thirty_second_budget_nfr01():
    signal = _ten_minute_recording()
    ensemble = load_ensemble(ARTEFACT_DIR)
    calibrated = CLASSES  # every task calibrated: the largest output space D5 ever restricts to

    started = time.perf_counter()

    # D4: filtered once, whole-recording, never per-window.
    filtered = bandpass_filter(signal)
    envelope = linear_envelope(filtered)

    raw_windows = sliding_windows(filtered)
    env_windows = sliding_windows(envelope)

    features = extract_freq72(np.ascontiguousarray(raw_windows))
    features_z = zscore_features(features)

    envelope_channel_major = np.ascontiguousarray(env_windows.transpose(0, 2, 1))
    envelope_z = zscore_envelopes(envelope_channel_major)

    prediction = ensemble.predict(features_z, envelope_z)

    restricted = restrict_to_calibrated(prediction.probabilities, calibrated)
    label_indices = restricted.argmax(axis=1)

    smoothed = majority_vote_smooth(label_indices)
    dwelled = enforce_minimum_dwell(smoothed)

    build_bouts(
        "perf-test-session",
        dwelled,
        restricted,
        dns_wak_margin=0.15,
        low_confidence_threshold=0.60,
    )

    elapsed = time.perf_counter() - started

    assert raw_windows.shape[0] > 0
    assert elapsed <= BUDGET_SECONDS, (
        f"a {SESSION_SECONDS}s session took {elapsed:.1f}s to process; NFR-01 budgets {BUDGET_SECONDS}s"
    )
