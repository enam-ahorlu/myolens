"""Windowing and the sampling-rate constants.

Two constants here look wrong and are both deliberate. They are explained rather than hidden,
because a future reader who "fixes" either one will silently change every result.

**SAMPLING_RATE_HZ is 1920, not 2000.** SIAT-LLMD's own metadata reports 1920.0001344 Hz. Some
descriptions of the corpus round it to 2 kHz. The 250 ms window is what is authoritative, and
480 / 1920 = 0.250 s exactly, whereas 480 / 2000 = 0.240 s. The window length is right; the
2 kHz figure is not.

**SPECTRAL_REFERENCE_HZ is 2000, and must stay 2000.** The trained models were fitted on features
whose mean and median frequency columns were computed against a hardcoded 2000 Hz. That constant
is therefore part of the frozen feature specification, not a parameter. It contributes a fixed
2000/1920 ~= 1.0417 scale factor to those columns, which per-column z-scoring absorbs exactly, so
no classification result depends on it. Correcting it to 1920 would shift the serving features
away from the distribution the models were fitted on, for no gain.

The one visible consequence: any mean/median frequency *reported in hertz* is about 4% high.
MyoLens does not report either, so nothing user-facing is affected.
"""

from __future__ import annotations

import numpy as np

#: True sampling rate of SIAT-LLMD, from the corpus metadata.
SAMPLING_RATE_HZ: float = 1920.0

#: The constant the frozen feature specification uses for MNF/MDF. See the module docstring.
SPECTRAL_REFERENCE_HZ: float = 2000.0

WINDOW_SAMPLES: int = 480  # 250 ms at 1920 Hz
STEP_SAMPLES: int = 240  # 125 ms hop, 50% overlap

WINDOW_MS: float = WINDOW_SAMPLES / SAMPLING_RATE_HZ * 1000.0
STEP_MS: float = STEP_SAMPLES / SAMPLING_RATE_HZ * 1000.0

#: Hard ceiling on an uploaded session, from the non-functional budget.
MAX_SESSION_SECONDS: int = 600


def window_count(n_samples: int) -> int:
    """Number of complete windows extractable from a recording of ``n_samples``.

    Trailing samples that cannot fill a whole window are discarded. A partial window would be
    a shorter observation than every window the model was trained on, and padding it would
    fabricate signal.
    """
    if n_samples < WINDOW_SAMPLES:
        return 0
    return 1 + (n_samples - WINDOW_SAMPLES) // STEP_SAMPLES


def window_bounds(index: int) -> tuple[int, int]:
    """Half-open ``[start, end)`` sample bounds of window ``index``."""
    if index < 0:
        raise ValueError(f"window index must be non-negative, got {index}")
    start = index * STEP_SAMPLES
    return start, start + WINDOW_SAMPLES


def window_time_ms(index: int) -> tuple[float, float]:
    """Half-open ``[start, end)`` bounds of window ``index`` in milliseconds."""
    start, end = window_bounds(index)
    return start / SAMPLING_RATE_HZ * 1000.0, end / SAMPLING_RATE_HZ * 1000.0


def sliding_windows(signal: np.ndarray) -> np.ndarray:
    """Cut ``(n_samples, n_channels)`` into ``(n_windows, WINDOW_SAMPLES, n_channels)``.

    Returns a read-only strided view, not a copy: a ten-minute nine-channel recording is roughly
    41 MB, and materialising 50%-overlapped copies of it would double that for no reason. The
    view is marked read-only because writing through overlapping strides corrupts neighbouring
    windows in a way that is very hard to debug.
    """
    if signal.ndim != 2:
        raise ValueError(f"expected (n_samples, n_channels), got shape {signal.shape}")

    n_samples = signal.shape[0]
    count = window_count(n_samples)
    if count == 0:
        return np.empty((0, WINDOW_SAMPLES, signal.shape[1]), dtype=signal.dtype)

    sample_stride, channel_stride = signal.strides
    view = np.lib.stride_tricks.as_strided(
        signal,
        shape=(count, WINDOW_SAMPLES, signal.shape[1]),
        strides=(sample_stride * STEP_SAMPLES, sample_stride, channel_stride),
        writeable=False,
    )
    return view


def exceeds_duration_cap(n_samples: int) -> bool:
    """True when a recording is longer than the accepted maximum."""
    return n_samples / SAMPLING_RATE_HZ > MAX_SESSION_SECONDS
