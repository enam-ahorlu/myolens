"""Windowing, and the sampling rate the corpus actually has."""

from __future__ import annotations

import numpy as np

from app.domain.windowing import (
    SAMPLING_RATE_HZ,
    SPECTRAL_REFERENCE_HZ,
    STEP_SAMPLES,
    WINDOW_SAMPLES,
    exceeds_duration_cap,
    sliding_windows,
    window_bounds,
    window_count,
)


def test_the_window_is_exactly_250_ms_at_the_true_sampling_rate():
    """480 / 1920 is exactly 0.250 s. 480 / 2000 is 0.240 s. The window length is authoritative,
    which is how we know 1920 is the right rate and the widely quoted 2 kHz is not."""
    assert WINDOW_SAMPLES / SAMPLING_RATE_HZ == 0.250
    assert STEP_SAMPLES / SAMPLING_RATE_HZ == 0.125


def test_the_spectral_reference_stays_at_2000_and_differs_from_the_sampling_rate():
    """Regression guard. The frozen feature specification computes MNF/MDF against 2000 Hz, so
    that constant is part of the model, not a parameter. 'Correcting' it to 1920 would move
    serving features off the distribution the models were fitted on."""
    assert SPECTRAL_REFERENCE_HZ == 2000.0
    assert SPECTRAL_REFERENCE_HZ != SAMPLING_RATE_HZ


def test_window_count_discards_an_incomplete_trailing_window():
    assert window_count(WINDOW_SAMPLES - 1) == 0
    assert window_count(WINDOW_SAMPLES) == 1
    assert window_count(WINDOW_SAMPLES + STEP_SAMPLES) == 2
    assert window_count(WINDOW_SAMPLES + STEP_SAMPLES - 1) == 1


def test_windows_overlap_by_half():
    first_start, first_end = window_bounds(0)
    second_start, _ = window_bounds(1)
    assert second_start == first_start + STEP_SAMPLES
    assert second_start < first_end


def test_sliding_windows_returns_the_expected_shape_and_content():
    signal = np.arange(WINDOW_SAMPLES * 3, dtype=np.float64).reshape(-1, 1)
    windows = sliding_windows(signal)

    assert windows.shape == (window_count(signal.shape[0]), WINDOW_SAMPLES, 1)
    np.testing.assert_array_equal(windows[0, :, 0], signal[:WINDOW_SAMPLES, 0])
    np.testing.assert_array_equal(
        windows[1, :, 0], signal[STEP_SAMPLES : STEP_SAMPLES + WINDOW_SAMPLES, 0]
    )


def test_sliding_windows_is_a_read_only_view_not_a_copy():
    """A ten-minute nine-channel recording is ~41 MB; overlapped copies would double it. The view
    is read-only because writing through overlapping strides corrupts neighbouring windows."""
    signal = np.zeros((WINDOW_SAMPLES * 4, 9), dtype=np.float64)
    windows = sliding_windows(signal)

    assert not windows.flags.writeable
    assert windows.base is not None


def test_an_empty_result_keeps_its_shape():
    windows = sliding_windows(np.zeros((10, 9)))
    assert windows.shape == (0, WINDOW_SAMPLES, 9)


def test_the_duration_cap_is_enforced_in_samples():
    assert not exceeds_duration_cap(int(SAMPLING_RATE_HZ * 600))
    assert exceeds_duration_cap(int(SAMPLING_RATE_HZ * 601))
