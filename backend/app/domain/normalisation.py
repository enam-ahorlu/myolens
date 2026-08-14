"""Transductive, whole-session normalisation (ADR-003, MODEL_CARD.md §5).

Neither ONNX graph performs normalisation internally, and no fitted normaliser ships with
them — the thesis's headline 0.858 macro-F1 comes from the *transductive* regime, where every
recording (including held-out ones) is standardised by its own statistics. MyoLens reproduces
that condition by computing statistics from the assessment session itself, over the whole
uploaded recording, and never sharing them between participants or sessions (ADR-003).

Ported verbatim from ``prepare_deployment_artifacts.py``'s ``per_subject_zscore_2d`` /
``per_subject_zscore_3d`` with the subject-grouping loop removed — at serving time there is
exactly one group, the session, so grouping by subject and grouping by "the whole array" are
the same operation.
"""

from __future__ import annotations

import numpy as np

_SD_FLOOR = 1e-8


def zscore_features(features: np.ndarray) -> np.ndarray:
    """Per feature column, over all of a session's windows. Population std (ddof=0);
    a column whose std falls below the floor is left unscaled (divided by 1.0) rather than
    exploding — see the SVM path in MODEL_CARD.md §5."""
    if features.ndim != 2:
        raise ValueError(f"expected (n_windows, n_features), got shape {features.shape}")
    mean = features.mean(axis=0, keepdims=True)
    std = features.std(axis=0, keepdims=True)
    std = np.where(std < _SD_FLOOR, 1.0, std)
    return (features - mean) / std


def zscore_envelopes(envelopes: np.ndarray) -> np.ndarray:
    """Per channel, pooled over a session's windows *and* time (axes 0 and 2) — the ResNet
    path in MODEL_CARD.md §5. Same population-std, same floor."""
    if envelopes.ndim != 3:
        raise ValueError(
            f"expected (n_windows, n_channels, n_samples), got shape {envelopes.shape}"
        )
    mean = envelopes.mean(axis=(0, 2), keepdims=True)
    std = envelopes.std(axis=(0, 2), keepdims=True)
    std = np.where(std < _SD_FLOOR, 1.0, std)
    return (envelopes - mean) / std
