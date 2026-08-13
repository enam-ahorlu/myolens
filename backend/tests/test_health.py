"""The health endpoint reports the contract, not just liveness."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.serving.predictor import CLASSES

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_the_frozen_class_order():
    """The class order is the output order of both ONNX graphs. A mismatch would relabel every
    prediction consistently and silently, so it is worth asserting from the outside."""
    assert response_classes() == ["DNS", "STDUP", "UPS", "WAK"] == list(CLASSES)


def response_classes() -> list[str]:
    return client.get("/v1/health").json()["classes"]


def test_health_reports_the_montage_and_windowing_contract():
    body = client.get("/v1/health").json()
    assert body["montage_channels"] == 9
    assert body["sampling_rate_hz"] == 1920.0
    assert body["window_samples"] == 480
    assert body["step_samples"] == 240


def test_every_response_carries_a_request_id():
    assert client.get("/v1/health").headers["X-Request-ID"]
