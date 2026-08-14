"""Bandpass filtering and linear envelope extraction (preprocess_emg.py port).

No raw ground-truth fixture from the thesis pipeline is available to this repository (the
multi-hundred-megabyte raw trial data lives outside it), so these tests validate against
analytically known properties of synthetic signals rather than a golden file. The ONNX-facing
half of the pipeline (features -> probabilities) is separately validated bit-for-bit against
real thesis output in test_onnx_equivalence.py; these tests cover the half upstream of that."""

from __future__ import annotations

import numpy as np

from app.domain.signal import (
    BANDPASS_HIGH_HZ,
    BANDPASS_LOW_HZ,
    ENVELOPE_MS,
    bandpass_filter,
    linear_envelope,
)

FS = 1920.0


def _sine(freq_hz: float, seconds: float = 1.0, fs: float = FS, n_channels: int = 1) -> np.ndarray:
    t = np.arange(int(seconds * fs)) / fs
    wave = np.sin(2 * np.pi * freq_hz * t)
    return np.tile(wave[:, None], (1, n_channels))


def test_bandpass_passes_a_frequency_inside_the_band():
    """A 100 Hz tone sits well inside 20-450 Hz and should survive close to full amplitude."""
    signal = _sine(100.0, seconds=2.0)
    filtered = bandpass_filter(signal, fs=FS)

    steady = filtered[len(filtered) // 4 : -len(filtered) // 4]  # avoid filtfilt edge transients
    assert np.max(np.abs(steady)) > 0.8


def test_bandpass_attenuates_dc_offset():
    """0 Hz is far outside 20-450 Hz; a constant offset should be removed almost entirely."""
    signal = np.full((2000, 1), 5.0)
    filtered = bandpass_filter(signal, fs=FS)

    steady = filtered[200:-200]
    assert np.max(np.abs(steady)) < 0.5


def test_bandpass_attenuates_a_frequency_far_above_the_band():
    """900 Hz is well past the 450 Hz upper edge."""
    signal = _sine(900.0, seconds=1.0)
    filtered = bandpass_filter(signal, fs=FS)

    steady = filtered[100:-100]
    assert np.max(np.abs(steady)) < 0.3


def test_bandpass_rejects_non_finite_input():
    signal = np.full((100, 9), np.nan)
    import pytest

    with pytest.raises(ValueError):
        bandpass_filter(signal, fs=FS)


def test_bandpass_operates_independently_per_channel():
    """A signal only on channel 0 must not leak into channel 1's output."""
    signal = np.zeros((2000, 2))
    signal[:, 0] = _sine(100.0, seconds=2000 / FS)[:, 0]

    filtered = bandpass_filter(signal, fs=FS)

    assert np.max(np.abs(filtered[200:-200, 1])) < 1e-9


def test_envelope_of_zero_signal_is_zero():
    envelope = linear_envelope(np.zeros((500, 3)), fs=FS)
    np.testing.assert_array_equal(envelope, np.zeros((500, 3)))


def test_envelope_preserves_shape():
    signal = _sine(50.0, seconds=1.0, n_channels=4)
    envelope = linear_envelope(signal, fs=FS)
    assert envelope.shape == signal.shape


def test_envelope_is_non_negative():
    """Rectify-then-average of any real signal cannot go negative."""
    rng = np.random.default_rng(0)
    signal = rng.normal(size=(2000, 3))
    envelope = linear_envelope(signal, fs=FS)
    assert (envelope >= 0).all()


def test_envelope_of_a_sine_approaches_the_rectified_mean_away_from_edges():
    """Full-wave rectifying a sine of amplitude A and averaging over many cycles converges to
    (2/pi) * A ~= 0.6366 * A. A 50 ms window at 1920 Hz (96 samples) covers several cycles of
    a 50 Hz tone, so the smoothed envelope should sit close to that constant mid-signal."""
    amplitude = 2.0
    signal = amplitude * _sine(50.0, seconds=2.0)
    envelope = linear_envelope(signal, fs=FS)

    mid = envelope[len(envelope) // 2 - 200 : len(envelope) // 2 + 200]
    expected = (2 / np.pi) * amplitude
    assert abs(mid.mean() - expected) < 0.05


def test_envelope_window_length_matches_the_frozen_spec():
    """96 samples at 1920 Hz for a 50 ms window, per MODEL_CARD.md §4."""
    assert round(ENVELOPE_MS * FS / 1000.0) == 96


def test_bandpass_edges_match_the_frozen_spec():
    assert (BANDPASS_LOW_HZ, BANDPASS_HIGH_HZ) == (20.0, 450.0)
