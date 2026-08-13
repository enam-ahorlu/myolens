"""The serving boundary: class order, soft vote, and input validation."""

from __future__ import annotations

import numpy as np
import pytest

from app.serving.predictor import CLASSES, N_CLASSES, N_FEATURES, Prediction, soft_vote


def test_the_class_order_is_frozen():
    """Hardcoded to match the ONNX graphs' output order. A mismatch relabels every prediction
    consistently and silently, and every screen would still look normal."""
    assert CLASSES == ("DNS", "STDUP", "UPS", "WAK")
    assert N_CLASSES == 4


def test_the_feature_count_matches_the_frozen_specification():
    assert N_FEATURES == 72


def test_soft_vote_averages_unweighted():
    """Deliberately unweighted: weighting would be a hyperparameter fitted on no held-out data,
    and the measured 0.858 came from exactly this configuration."""
    a = np.array([[0.8, 0.1, 0.05, 0.05]])
    b = np.array([[0.4, 0.3, 0.2, 0.1]])

    np.testing.assert_allclose(soft_vote(a, b), [[0.6, 0.2, 0.125, 0.075]])


def test_soft_vote_preserves_a_probability_distribution():
    rng = np.random.default_rng(0)
    a = rng.dirichlet(np.ones(N_CLASSES), size=10)
    b = rng.dirichlet(np.ones(N_CLASSES), size=10)

    np.testing.assert_allclose(soft_vote(a, b).sum(axis=1), 1.0)


def test_soft_vote_rejects_disagreeing_shapes():
    with pytest.raises(ValueError):
        soft_vote(np.zeros((3, 4)), np.zeros((2, 4)))


def test_prediction_exposes_labels_and_confidence():
    probabilities = np.array([[0.1, 0.7, 0.1, 0.1], [0.05, 0.05, 0.2, 0.7]])
    prediction = Prediction(probabilities, model_version="test", model_hash="abc")

    np.testing.assert_array_equal(prediction.labels, [1, 3])
    np.testing.assert_allclose(prediction.confidence, [0.7, 0.7])


def test_prediction_rejects_a_wrong_class_count():
    with pytest.raises(ValueError):
        Prediction(np.zeros((5, 3)), model_version="test", model_hash="abc")
