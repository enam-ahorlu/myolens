"""Bandpass filtering and linear envelope extraction.

Ported from ``preprocess_emg.py`` in the thesis codebase (MSc Python Project), which is
disclosed pre-existing research artefact per Rule 12 — see HANDOFF_MYOLENS.md §1 and
``docs/DECLARATION.md``. The two operations here run once, on the *whole* uploaded recording,
before windowing — never per window. Running them per window would filter across a
discontinuity at every window boundary and would size the envelope's rolling mean against 480
samples instead of the whole trial, both of which would silently produce a different signal
than the one the models were trained on.

**Order matters and is fixed**: bandpass first, then rectify-and-smooth the *bandpassed*
signal. Reversing it, or enveloping the unfiltered signal, changes every downstream feature.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

from app.domain.windowing import SAMPLING_RATE_HZ

#: MODEL_CARD.md §4: "band-pass 20-450 Hz, 4th order".
BANDPASS_LOW_HZ = 20.0
BANDPASS_HIGH_HZ = 450.0
BANDPASS_ORDER = 4

#: MODEL_CARD.md §4: "linear envelope 50 ms".
ENVELOPE_MS = 50.0


def _design_bandpass(fs: float) -> tuple[np.ndarray, np.ndarray]:
    nyquist = 0.5 * fs
    low = BANDPASS_LOW_HZ / nyquist
    high = BANDPASS_HIGH_HZ / nyquist
    if not (0 < low < high < 1):
        raise ValueError(f"invalid bandpass edges for fs={fs}: low={low}, high={high}")
    return butter(BANDPASS_ORDER, [low, high], btype="bandpass")


def bandpass_filter(signal: np.ndarray, fs: float = SAMPLING_RATE_HZ) -> np.ndarray:
    """Zero-phase Butterworth bandpass, applied independently per channel.

    ``signal`` is ``(n_samples, n_channels)``. ``filtfilt`` (not ``lfilter``) because the
    thesis pipeline used it: it runs the filter forward and backward, doubling the effective
    order but introducing no phase shift, which matters for a signal that is about to be
    windowed against time-aligned labels.
    """
    if signal.ndim != 2:
        raise ValueError(f"expected (n_samples, n_channels), got shape {signal.shape}")
    if not np.isfinite(signal).all():
        raise ValueError("signal contains non-finite values; clean input before filtering")

    b, a = _design_bandpass(fs)
    out = np.empty_like(signal, dtype=np.float64)
    for channel in range(signal.shape[1]):
        out[:, channel] = filtfilt(b, a, signal[:, channel].astype(np.float64))
    return out


def linear_envelope(
    bandpassed: np.ndarray, fs: float = SAMPLING_RATE_HZ, envelope_ms: float = ENVELOPE_MS
) -> np.ndarray:
    """Rectify and smooth an already-bandpassed signal into a linear envelope.

    Matches ``preprocess_emg.rectify_and_envelope`` exactly: full-wave rectification (``abs``)
    followed by a **centred** moving average over ``round(envelope_ms * fs / 1000)`` samples
    (96 at 1920 Hz), with ``min_periods=1`` so the first and last half-window still produce a
    value from whatever samples are available rather than becoming NaN.
    """
    if bandpassed.ndim != 2:
        raise ValueError(f"expected (n_samples, n_channels), got shape {bandpassed.shape}")

    window = max(round(envelope_ms * fs / 1000.0), 1)
    rectified = np.abs(bandpassed)

    # pandas directly, rather than a hand-rolled reimplementation: this is the literal call
    # preprocess_emg.rectify_and_envelope makes (per channel; DataFrame.rolling applies it to
    # every column at once), and its centred/min_periods edge behaviour is exactly what needs
    # reproducing — re-deriving that behaviour by hand risks a subtly wrong envelope that
    # silently degrades the ResNet path, which nothing downstream would flag as wrong.
    envelope = pd.DataFrame(rectified).rolling(window, center=True, min_periods=1).mean()
    return envelope.to_numpy(dtype=np.float64)
