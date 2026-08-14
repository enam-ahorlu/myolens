"""Transductive, whole-session normalisation (ADR-003)."""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.normalisation import zscore_envelopes, zscore_features


def test_zscore_features_has_zero_mean_and_unit_std_per_column():
    rng = np.random.default_rng(0)
    features = rng.normal(loc=[10, -5, 100], scale=[1, 2, 50], size=(500, 3))

    z = zscore_features(features)

    np.testing.assert_allclose(z.mean(axis=0), 0.0, atol=1e-8)
    np.testing.assert_allclose(z.std(axis=0), 1.0, atol=1e-8)


def test_zscore_features_guards_a_near_constant_column():
    """A column whose std falls below the floor would otherwise blow up to +-inf."""
    features = np.ones((50, 2))
    features[:, 1] = np.arange(50)  # this column has real variance

    z = zscore_features(features)

    assert np.isfinite(z).all()
    np.testing.assert_array_equal(z[:, 0], 0.0)  # unscaled: (1 - 1) / 1.0 == 0


def test_zscore_features_rejects_wrong_shape():
    with pytest.raises(ValueError):
        zscore_features(np.zeros((10, 5, 2)))


def test_zscore_envelopes_pools_over_windows_and_time_per_channel():
    rng = np.random.default_rng(1)
    envelopes = rng.normal(loc=[[10], [50]], scale=[[1], [5]], size=(20, 2, 480))

    z = zscore_envelopes(envelopes)

    # Pooled over axes (0, 2): the mean/std are computed per channel across every window and
    # every timestep together, not per window.
    np.testing.assert_allclose(z.mean(axis=(0, 2)), 0.0, atol=1e-8)
    np.testing.assert_allclose(z.std(axis=(0, 2)), 1.0, atol=1e-8)


def test_zscore_envelopes_guards_a_near_constant_channel():
    envelopes = np.zeros((10, 2, 480))
    envelopes[:, 1, :] = np.random.default_rng(2).normal(size=(10, 480))

    z = zscore_envelopes(envelopes)

    assert np.isfinite(z).all()
    np.testing.assert_array_equal(z[:, 0, :], 0.0)


def test_zscore_envelopes_rejects_wrong_shape():
    with pytest.raises(ValueError):
        zscore_envelopes(np.zeros((10, 5)))
