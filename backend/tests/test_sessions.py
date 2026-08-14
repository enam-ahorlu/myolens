"""Session upload and automatic segmentation (D1-D8, SRS §4.2 D).

The real ONNX ensemble is monkeypatched out (same reasoning as ``test_calibrations.py``'s OOD
stats fixture): this suite exercises the real signal/feature/normalisation/smoothing/bout
pipeline end to end, but not the actual model graphs, so it does not depend on
``backend/artifacts/`` being present.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.adapters.firestore_repo import COLLECTIONS, get_document_store
from app.adapters.storage import get_object_store
from app.auth import CurrentUser, get_current_user
from app.domain.calibration_record import TaskCalibrationSummary, new_calibration_record
from app.domain.montage import MONTAGE
from app.domain.participants import AffectedSide, AgeBand, Sex, new_participant
from app.main import app
from app.routers import sessions as sessions_module
from app.serving.predictor import CLASSES, Prediction
from tests.fakes import FakeDocumentStore

CLINICIAN_A = CurrentUser(uid="clinician-a", email="a@clinic.example", role="clinician")
CLINICIAN_B = CurrentUser(uid="clinician-b", email="b@clinic.example", role="clinician")

RNG = np.random.default_rng(4242)

N = len(CLASSES)
DNS = CLASSES.index("DNS")
WAK = CLASSES.index("WAK")
STDUP = CLASSES.index("STDUP")


class FakeObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, object_name: str, data: bytes) -> None:
        self._objects[object_name] = data

    def signed_upload_url(self, object_name: str, content_type: str) -> str:
        return f"https://fake-bucket.example/{object_name}"

    def read_bytes(self, object_name: str) -> bytes:
        return self._objects[object_name]


class FakeEnsemble:
    """Always favours DNS, heavily. Used to prove D5 restricts the output space even when the
    model's raw favourite is an uncalibrated task."""

    def predict(self, features: np.ndarray, envelopes: np.ndarray) -> Prediction:
        assert features.shape[0] == envelopes.shape[0]
        row = np.full(N, 0.05)
        row[DNS] = 0.85
        probabilities = np.tile(row, (features.shape[0], 1))
        return Prediction(
            probabilities=probabilities, model_version="fake-1.0.0", model_hash="deadbeef"
        )


def _session_csv(n_samples: int = 6000) -> bytes:
    """~3.1 s of synthetic signal at 1920 Hz -- comfortably more than one window (480 samples)."""
    signal = RNG.normal(0.0, 50.0, size=(n_samples, len(MONTAGE)))
    frame = pd.DataFrame(signal, columns=list(MONTAGE))
    frame.insert(0, "Time", np.arange(n_samples) / 1920.0)
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue()


def _client_as(user: CurrentUser, store: FakeDocumentStore, objects: FakeObjectStore) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_document_store] = lambda: store
    app.dependency_overrides[get_object_store] = lambda: objects
    return TestClient(app)


def _reset():
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _fake_ensemble(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sessions_module, "get_ensemble", lambda _artefact_dir: FakeEnsemble())
    yield


def _register_participant(store: FakeDocumentStore, owner: str = "clinician-a") -> str:
    participant = new_participant(
        code="P-001",
        age_band=AgeBand.Y30_44,
        sex=Sex.FEMALE,
        affected_side=AffectedSide.LEFT,
        notes="",
        created_by=owner,
    )
    store.set(COLLECTIONS.PARTICIPANTS, participant.id, participant.to_document())
    return participant.id


def _give_active_calibration(
    store: FakeDocumentStore, participant_id: str, calibrated_tasks: tuple[str, ...]
) -> None:
    per_task = {
        task: TaskCalibrationSummary(
            window_count=30 if task in calibrated_tasks else 0,
            block_count=3 if task in calibrated_tasks else 0,
            status="calibrated" if task in calibrated_tasks else "not_attempted",
        )
        for task in CLASSES
    }
    record = new_calibration_record(
        participant_id=participant_id,
        version=1,
        created_by="clinician-a",
        source_object="calibration/x.csv",
        per_task=per_task,
        envelope_peak=tuple(1.0 for _ in range(9)),
        mahalanobis=1.0,
        difficulty_band="typical",
        ood_flag=False,
    )
    store.set(COLLECTIONS.CALIBRATIONS, record.id, record.to_document())


def test_create_session_requires_authentication():
    _reset()
    response = TestClient(app).post(
        "/v1/sessions", json={"participant_id": "p1", "object_name": "session/p1/x.csv"}
    )
    assert response.status_code == 401
    _reset()


def test_create_session_registers_a_valid_upload():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put("session/p1/one.csv", _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": "session/p1/one.csv"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["sample_count"] == 6000
    stored = store.get(COLLECTIONS.SESSIONS, body["id"])
    assert stored is not None
    assert stored["participantId"] == participant_id
    _reset()


def test_create_session_rejects_a_montage_mismatch():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    frame = pd.DataFrame(RNG.normal(size=(100, 3)), columns=["a", "b", "c"])
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    objects.put("session/p1/bad.csv", buffer.getvalue())
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": "session/p1/bad.csv"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "montage_rejected"
    _reset()


def test_segment_requires_a_calibration():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put("session/p1/one.csv", _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    created = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": "session/p1/one.csv"}
    ).json()

    response = client.post(f"/v1/sessions/{created['id']}/segment")

    assert response.status_code == 412
    assert response.json()["code"] == "not_calibrated"
    _reset()


def test_segment_restricts_the_output_space_to_calibrated_tasks_d5():
    """FakeEnsemble always favours DNS. The participant is calibrated for WAK and STDUP only --
    DNS must never appear as a bout's task."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put("session/p1/one.csv", _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    created = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": "session/p1/one.csv"}
    ).json()

    response = client.post(f"/v1/sessions/{created['id']}/segment")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "segmented"
    assert len(body["bouts"]) >= 1
    tasks_seen = {b["task"] for b in body["bouts"]}
    assert "DNS" not in tasks_seen
    assert tasks_seen <= {"WAK", "STDUP"}
    # DNS was the model's actual favourite everywhere, so between WAK and STDUP -- both
    # calibrated -- the restricted vote should consistently land on whichever of the two the
    # uniform 0.05 remainder ties toward; either is fine, only DNS is disallowed.

    stored_session = store.get(COLLECTIONS.SESSIONS, created["id"])
    assert stored_session["status"] == "segmented"
    assert stored_session["modelVersion"] == "fake-1.0.0"
    assert stored_session["calibrationVersion"] == 1

    bout_docs = store.query(COLLECTIONS.BOUTS, sessionId=created["id"])
    assert len(bout_docs) == len(body["bouts"])
    _reset()


def test_segment_writes_an_audit_entry():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put("session/p1/one.csv", _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    created = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": "session/p1/one.csv"}
    ).json()
    client.post(f"/v1/sessions/{created['id']}/segment")

    entries = store.query(COLLECTIONS.AUDIT, targetId=created["id"])
    actions = {e["action"] for e in entries}
    assert "session.create" in actions
    assert "session.segment" in actions
    _reset()


def test_a_clinician_cannot_segment_another_clinician_s_session():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store, owner="clinician-a")
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put("session/p1/one.csv", _session_csv())
    owner_client = _client_as(CLINICIAN_A, store, objects)

    created = owner_client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": "session/p1/one.csv"}
    ).json()

    other_client = _client_as(CLINICIAN_B, store, objects)
    response = other_client.post(f"/v1/sessions/{created['id']}/segment")

    assert response.status_code == 404
    _reset()
