"""The frozen Freq-72 feature specification.

Ported from ``extract_features.py`` in the thesis codebase (disclosed pre-existing research
artefact, Rule 12 — see HANDOFF_MYOLENS.md §1). Re-implemented vectorised across all windows
and channels at once rather than the original's per-channel Python loop, for serving latency —
but every formula, threshold and the frequency-domain constant below are copied verbatim, and
MODEL_CARD.md §4 states the same specification independently as a cross-check.

**Feature-major order**: eight blocks of nine channels, not nine channels of eight features —
``MAV(9) · RMS(9) · WL(9) · ZC(9) · WAMP(9) · MNF(9) · MDF(9) · logSP(9)``. Getting the axis
order backwards would still produce a `(n_windows, 72)` array that raises no error anywhere
and silently feeds the SVM 72 numbers in the wrong slots.

Operates on the **bandpassed raw signal**, not the envelope — MNF/MDF/ZC/WAMP are meaningless
on a rectified, always-non-negative envelope trace. The envelope windows are a separate input,
used only by the ResNet path (see ``onnx_predictor.OnnxResnetPredictor``).
"""

from __future__ import annotations

import numpy as np

from app.serving.predictor import N_FEATURES

#: MODEL_CARD.md §4: "Zero-crossing and Willison-amplitude thresholds both 1e-6."
ZC_THRESHOLD = 1e-6
WAMP_THRESHOLD = 1e-6

#: The frozen feature specification hardcodes 2000.0 for MNF/MDF/logSP, not the true 1920 Hz
#: sampling rate. See app/domain/windowing.py's module docstring for why this must not be
#: "corrected" — per-column z-scoring absorbs the resulting constant scale factor exactly, so
#: correcting it would move these features off the distribution the models were fitted on.
SPECTRAL_REFERENCE_HZ = 2000.0

FEATURE_BLOCKS: tuple[str, ...] = ("MAV", "RMS", "WL", "ZC", "WAMP", "MNF", "MDF", "logSP")


def extract_freq72(windows: np.ndarray, fs: float = SPECTRAL_REFERENCE_HZ) -> np.ndarray:
    """``(n_windows, n_samples, n_channels)`` bandpassed windows -> ``(n_windows, 72)`` features.

    ``fs`` defaults to the frozen 2000.0 Hz constant, not the true sampling rate — see the
    module docstring. It is a parameter only so a test can probe the frequency-domain features
    against a signal of a known, convenient frequency without fighting the constant.
    """
    if windows.ndim != 3:
        raise ValueError(f"expected (n_windows, n_samples, n_channels), got shape {windows.shape}")
    if not np.isfinite(windows).all():
        raise ValueError("window data contains non-finite values")

    # Internally channel-major, (n_windows, n_channels, n_samples): matches the thesis
    # extractor's per-window (C, T) convention and is the natural axis for `np.fft.rfft`.
    x = np.transpose(windows, (0, 2, 1)).astype(np.float64)

    mav = np.mean(np.abs(x), axis=-1)
    rms = np.sqrt(np.mean(x**2, axis=-1))
    wl = np.sum(np.abs(np.diff(x, axis=-1)), axis=-1)
    zc = _zero_crossings(x, ZC_THRESHOLD)
    wamp = np.sum(np.abs(np.diff(x, axis=-1)) > WAMP_THRESHOLD, axis=-1).astype(np.float64)
    mnf, mdf, log_sp = _spectral_features(x, fs)

    # Feature-major concatenation: each block is (n_windows, n_channels); stacking on a new
    # leading axis then flattening the last two gives exactly "8 blocks of 9 channels".
    blocks = np.stack([mav, rms, wl, zc, wamp, mnf, mdf, log_sp], axis=1)
    features = blocks.reshape(blocks.shape[0], -1)

    if features.shape[1] != N_FEATURES:
        raise AssertionError(f"expected {N_FEATURES} features, produced {features.shape[1]}")
    return features.astype(np.float64)


def _zero_crossings(x: np.ndarray, threshold: float) -> np.ndarray:
    """Sign changes between consecutive samples where the jump clears ``threshold``. Zero is
    treated as positive, matching ``extract_features.feat_zc`` exactly (``s[s == 0] = 1``)."""
    sign = np.sign(x)
    sign[sign == 0] = 1
    sign_change = (sign[..., 1:] * sign[..., :-1]) < 0
    big_enough = np.abs(x[..., 1:] - x[..., :-1]) >= threshold
    return np.sum(sign_change & big_enough, axis=-1).astype(np.float64)


def _spectral_features(x: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MNF, MDF and log1p(total power), via ``rfft`` with no window function, no detrend, no
    zero-padding — MODEL_CARD.md §4 states this explicitly, because any of the three would
    change every value below without changing the array shape."""
    n_samples = x.shape[-1]
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / fs)
    spectrum = np.abs(np.fft.rfft(x, axis=-1)) ** 2  # (n_windows, n_channels, n_freqs)

    total_power = spectrum.sum(axis=-1)
    has_power = total_power > 1e-12

    mnf_num = np.einsum("f,wcf->wc", freqs, spectrum)
    mnf = np.zeros_like(total_power)
    mnf[has_power] = mnf_num[has_power] / total_power[has_power]

    cumulative = np.cumsum(spectrum, axis=-1)
    half_power = (total_power * 0.5)[..., None]
    # searchsorted per (window, channel) row: argmax of the first True is a vectorised
    # equivalent of np.searchsorted applied row-wise, since `cumulative` is sorted (monotone
    # non-decreasing) along the last axis by construction.
    reaches_half = cumulative >= half_power
    idx = np.argmax(reaches_half, axis=-1)
    idx = np.clip(idx, 0, len(freqs) - 1)
    mdf = np.where(has_power, freqs[idx], 0.0)

    log_sp = np.log1p(total_power)

    return mnf, mdf, log_sp
