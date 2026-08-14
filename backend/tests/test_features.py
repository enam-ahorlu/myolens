"""The frozen Freq-72 feature specification (extract_features.py port)."""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.features import (
    FEATURE_BLOCKS,
    SPECTRAL_REFERENCE_HZ,
    WAMP_THRESHOLD,
    ZC_THRESHOLD,
    extract_freq72,
)
from app.serving.predictor import N_FEATURES

N_CHANNELS = 9
WINDOW_SAMPLES = 480


def _windows(signal_per_channel: np.ndarray) -> np.ndarray:
    """(n_samples, n_channels) -> (1, n_samples, n_channels), the shape extract_freq72 expects."""
    return signal_per_channel[None, :, :]


def test_output_shape_is_72_features():
    windows = np.zeros((5, WINDOW_SAMPLES, N_CHANNELS))
    features = extract_freq72(windows)
    assert features.shape == (5, N_FEATURES)


def test_zero_signal_produces_zero_amplitude_and_shape_features():
    windows = np.zeros((1, WINDOW_SAMPLES, N_CHANNELS))
    features = extract_freq72(windows)[0]

    # Feature-major: block b, channel c lives at index b * N_CHANNELS + c.
    def block(name):
        i = FEATURE_BLOCKS.index(name)
        return features[i * N_CHANNELS : (i + 1) * N_CHANNELS]

    np.testing.assert_array_equal(block("MAV"), np.zeros(N_CHANNELS))
    np.testing.assert_array_equal(block("RMS"), np.zeros(N_CHANNELS))
    np.testing.assert_array_equal(block("WL"), np.zeros(N_CHANNELS))
    np.testing.assert_array_equal(block("ZC"), np.zeros(N_CHANNELS))
    np.testing.assert_array_equal(block("WAMP"), np.zeros(N_CHANNELS))
    np.testing.assert_array_equal(block("MNF"), np.zeros(N_CHANNELS))
    np.testing.assert_array_equal(block("MDF"), np.zeros(N_CHANNELS))
    np.testing.assert_array_equal(block("logSP"), np.zeros(N_CHANNELS))  # log1p(0) == 0


def test_mav_and_rms_of_a_constant_signal():
    value = 3.0
    signal = np.full((WINDOW_SAMPLES, N_CHANNELS), value)
    features = extract_freq72(_windows(signal))[0]

    mav = features[0:N_CHANNELS]
    rms = features[N_CHANNELS : 2 * N_CHANNELS]
    np.testing.assert_allclose(mav, value)
    np.testing.assert_allclose(rms, value)


def test_waveform_length_of_a_step_function():
    """WL sums |diff|. A single step of height h contributes exactly h."""
    signal = np.zeros((WINDOW_SAMPLES, N_CHANNELS))
    signal[WINDOW_SAMPLES // 2 :, :] = 5.0
    features = extract_freq72(_windows(signal))[0]

    wl = features[2 * N_CHANNELS : 3 * N_CHANNELS]
    np.testing.assert_allclose(wl, 5.0)


def test_zero_crossings_counts_only_changes_that_clear_the_threshold():
    t = np.arange(WINDOW_SAMPLES)
    alternating = np.where(
        t % 2 == 0, 1.0, -1.0
    )  # crosses every sample: WINDOW_SAMPLES - 1 crossings
    signal = np.tile(alternating[:, None], (1, N_CHANNELS))
    features = extract_freq72(_windows(signal))[0]

    zc = features[3 * N_CHANNELS : 4 * N_CHANNELS]
    np.testing.assert_array_equal(zc, WINDOW_SAMPLES - 1)


def test_zero_crossings_ignores_a_tiny_wiggle_below_threshold():
    tiny = ZC_THRESHOLD / 10
    signal = np.zeros((WINDOW_SAMPLES, N_CHANNELS))
    signal[::2, :] = tiny
    signal[1::2, :] = -tiny
    features = extract_freq72(_windows(signal))[0]

    zc = features[3 * N_CHANNELS : 4 * N_CHANNELS]
    np.testing.assert_array_equal(zc, 0.0)


def test_willison_amplitude_counts_jumps_strictly_above_threshold():
    signal = np.zeros((WINDOW_SAMPLES, N_CHANNELS))
    signal[1::2, :] = WAMP_THRESHOLD * 2  # every other sample jumps well past the threshold
    features = extract_freq72(_windows(signal))[0]

    wamp = features[4 * N_CHANNELS : 5 * N_CHANNELS]
    assert (wamp > 0).all()


def test_mean_and_median_frequency_of_a_pure_tone_at_an_exact_fft_bin():
    """A sinusoid whose frequency lands exactly on an rfft bin concentrates ~all spectral power
    there, so MNF and MDF should both land on that frequency."""
    fs = SPECTRAL_REFERENCE_HZ
    bin_hz = fs / WINDOW_SAMPLES  # frequency resolution of a single-window rfft
    target_bin = 40
    freq = target_bin * bin_hz

    t = np.arange(WINDOW_SAMPLES) / fs
    tone = np.sin(2 * np.pi * freq * t)
    signal = np.tile(tone[:, None], (1, N_CHANNELS))

    features = extract_freq72(_windows(signal), fs=fs)[0]
    mnf = features[5 * N_CHANNELS : 6 * N_CHANNELS]
    mdf = features[6 * N_CHANNELS : 7 * N_CHANNELS]

    np.testing.assert_allclose(mnf, freq, atol=1.0)
    np.testing.assert_allclose(mdf, freq, atol=1.0)


def test_log_spectral_power_is_monotonic_in_signal_energy():
    quiet = 0.1 * np.sin(2 * np.pi * 50 * np.arange(WINDOW_SAMPLES) / SPECTRAL_REFERENCE_HZ)
    loud = 5.0 * np.sin(2 * np.pi * 50 * np.arange(WINDOW_SAMPLES) / SPECTRAL_REFERENCE_HZ)

    quiet_features = extract_freq72(_windows(np.tile(quiet[:, None], (1, N_CHANNELS))))[0]
    loud_features = extract_freq72(_windows(np.tile(loud[:, None], (1, N_CHANNELS))))[0]

    quiet_sp = quiet_features[7 * N_CHANNELS : 8 * N_CHANNELS]
    loud_sp = loud_features[7 * N_CHANNELS : 8 * N_CHANNELS]
    assert (loud_sp > quiet_sp).all()


def test_feature_order_is_feature_major_not_channel_major():
    """Distinguishable per-channel MAV values must land at indices 0..8 (the MAV block), not
    scattered one-per-block -- this is the exact bug the module docstring warns about."""
    signal = np.zeros((WINDOW_SAMPLES, N_CHANNELS))
    for c in range(N_CHANNELS):
        signal[:, c] = c + 1  # channel c is constant at value c+1

    features = extract_freq72(_windows(signal))[0]
    mav_block = features[0:N_CHANNELS]
    np.testing.assert_allclose(mav_block, np.arange(1, N_CHANNELS + 1))


def test_rejects_wrong_dimensionality():
    with pytest.raises(ValueError):
        extract_freq72(np.zeros((WINDOW_SAMPLES, N_CHANNELS)))  # missing the window axis


def test_rejects_non_finite_input():
    windows = np.full((1, WINDOW_SAMPLES, N_CHANNELS), np.inf)
    with pytest.raises(ValueError):
        extract_freq72(windows)
