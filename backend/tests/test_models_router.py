"""The model card (H1): unauthenticated, and it says exactly what H1 asks for."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def response_body() -> dict:
    return client.get("/v1/models/current").json()


def test_model_card_is_reachable_without_auth():
    """H1 is meant to be reachable from every page footer -- including the login screen, before
    a clinician has signed in. A route that demanded a bearer token would defeat that."""
    response = client.get("/v1/models/current")
    assert response.status_code == 200


def test_model_card_labels_both_accuracy_regimes():
    regimes = {r["predictor"]: r for r in response_body()["accuracy_regimes"]}
    assert set(regimes) == {"ensemble", "svm_only"}
    for regime in regimes.values():
        assert 0.0 < regime["macro_f1"] <= 1.0
        assert 0.0 < regime["balanced_acc"] <= 1.0
        assert regime["n_windows"] > 0
    # The measured ordering from the thesis: the ensemble beats the SVM-only fallback.
    assert regimes["ensemble"]["macro_f1"] > regimes["svm_only"]["macro_f1"]


def test_model_card_reports_the_active_predictor_and_a_sha256():
    body = response_body()
    assert body["active_predictor"] == "ensemble"
    assert len(body["active_sha256"]) == 64  # hex-encoded SHA-256
    int(body["active_sha256"], 16)  # raises if it isn't hex


def test_model_card_reports_held_out_validation_and_training_protocol():
    body = response_body()
    assert body["held_out_validation"]["holdout_subjects"]
    assert body["held_out_validation"]["training_subjects_n"] > 0
    assert body["training_protocol"]["window_ms"] == 250
    assert body["training_protocol"]["step_ms"] == 125


def test_model_card_reports_the_frozen_montage_and_class_order():
    body = response_body()
    assert body["classes"] == ["DNS", "STDUP", "UPS", "WAK"]
    assert len(body["montage_channels"]) == 9
    assert body["montage_channels"][0] == "sEMG: tensor fascia lata"


def test_model_card_names_failure_modes_and_intended_use():
    body = response_body()
    assert any("DNS" in mode for mode in body["failure_modes"])
    assert "not a medical device" in body["intended_use"].lower()


def test_every_response_carries_a_request_id():
    assert client.get("/v1/models/current").headers["X-Request-ID"]


def test_the_card_reports_the_loso_figures_with_their_regimes_named():
    """FR-09 and NFR-04, on the surface an examiner actually reads.

    The card previously carried only the held-out numbers -- measured on three subjects, and
    *higher* than the LOSO figures. A reader saw 0.876 beside "the default" with no route to the
    defensible 0.858 at n = 40. Reporting the optimistic figure alone, without the protocol that
    makes it optimistic, is precisely what NFR-04 exists to prevent, and H1 asks for "both
    accuracy regimes labelled".
    """
    body = response_body()

    regimes = {r["regime"]: r for r in body["loso_accuracy"]}
    assert set(regimes) == {"transductive", "causal"}
    assert regimes["transductive"]["macro_f1"] == 0.858
    assert regimes["causal"]["macro_f1"] == 0.817
    assert all(r["n_subjects"] == 40 for r in regimes.values())

    # Exactly one of them describes what is deployed, and it is the transductive one (FR-01).
    assert regimes["transductive"]["describes_this_system"] is True
    assert regimes["causal"]["describes_this_system"] is False

    # The held-out figures survive, but must now say what they are.
    for regime in body["accuracy_regimes"]:
        assert "n = 3" in regime["label"], regime["label"]
