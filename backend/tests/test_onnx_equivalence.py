"""ONNX <-> native equivalence (TD-05, MODEL_CARD.md §7).

MODEL_CARD.md documents this check as "paid" with specific deltas, but no test in this
repository ever ran it until now — the number came from a one-off run of
``verify_onnx_equivalence.py`` in the MSc Python Project, not from CI. This test makes the
claim self-verifying: it loads the same 200-window reference fixture the model card cites and
asserts this repository's own predictor wrapper reproduces the documented tolerance, so a
future change to onnx_predictor.py (or a re-exported graph) that breaks equivalence fails CI
instead of silently invalidating a claim in a document nobody re-checks.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.serving.onnx_predictor import load_ensemble, load_resnet, load_svm

ARTEFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts"
REFERENCE = ARTEFACT_DIR / "reference_outputs.npz"

pytestmark = pytest.mark.skipif(
    not REFERENCE.exists(),
    reason="reference_outputs.npz not present (expected under backend/artifacts/)",
)

#: MODEL_CARD.md §7's own tolerance. Not relaxed here either.
TOLERANCE = 1e-4


@pytest.fixture(scope="module")
def reference():
    return np.load(REFERENCE)


def test_svm_matches_the_documented_tolerance(reference):
    svm = load_svm(ARTEFACT_DIR)
    prediction = svm.predict(reference["features"].astype(np.float32))

    delta = np.max(np.abs(prediction.probabilities - reference["svm_proba"]))
    assert delta < TOLERANCE
    # MODEL_CARD.md §7 documents 2.594e-05. Recorded as a bound, not an exact match — the
    # environment producing this run is not the one that produced the card's number, and a
    # test that demanded bit-for-bit equality across environments would be testing the
    # environment, not the export.
    assert delta < 1e-4


def test_resnet_matches_the_documented_tolerance(reference):
    resnet = load_resnet(ARTEFACT_DIR)
    prediction = resnet.predict(reference["envelopes"].astype(np.float32))

    delta = np.max(np.abs(prediction.probabilities - reference["resnet_proba"]))
    assert delta < TOLERANCE  # MODEL_CARD.md §7 documents 4.346e-07.


def test_ensemble_soft_vote_matches_the_documented_tolerance(reference):
    ensemble = load_ensemble(ARTEFACT_DIR)
    prediction = ensemble.predict(
        reference["features"].astype(np.float32), reference["envelopes"].astype(np.float32)
    )

    expected = (reference["svm_proba"] + reference["resnet_proba"]) / 2.0
    delta = np.max(np.abs(prediction.probabilities - expected))
    assert delta < TOLERANCE  # MODEL_CARD.md §7 documents 1.297e-05.


def test_argmax_agrees_with_the_reference_on_every_window(reference):
    """MODEL_CARD.md §7: '100% on all three'."""
    ensemble = load_ensemble(ARTEFACT_DIR)
    prediction = ensemble.predict(
        reference["features"].astype(np.float32), reference["envelopes"].astype(np.float32)
    )
    expected = (reference["svm_proba"] + reference["resnet_proba"]) / 2.0
    np.testing.assert_array_equal(prediction.labels, expected.argmax(axis=1))


def test_repeat_inference_is_byte_identical(reference):
    """Determinism (D4): the same input twice must produce the same output, not just a close
    one — that is what makes a disputed result reproducible months later."""
    ensemble = load_ensemble(ARTEFACT_DIR)
    features = reference["features"].astype(np.float32)
    envelopes = reference["envelopes"].astype(np.float32)

    first = ensemble.predict(features, envelopes)
    second = ensemble.predict(features, envelopes)

    np.testing.assert_array_equal(first.probabilities, second.probabilities)


def test_resnet_refuses_a_malformed_input_shape():
    resnet = load_resnet(ARTEFACT_DIR)
    with pytest.raises(ValueError):
        resnet.predict(np.zeros((5, 9, 100), dtype=np.float32))  # wrong window length


def test_svm_refuses_a_malformed_feature_count():
    svm = load_svm(ARTEFACT_DIR)
    with pytest.raises(ValueError):
        svm.predict(np.zeros((5, 10), dtype=np.float32))  # not 72 features
