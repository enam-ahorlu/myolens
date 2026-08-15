"""Calibration upload and retrieval (C1-C5, SRS §4.2 C).

Uses a fake :class:`~app.adapters.storage.ObjectStore` (structurally, not by inheritance -- the
same discipline ``FakeDocumentStore`` uses against ``DocumentStore``) so these tests exercise the
real parsing/feature/OOD pipeline without a bucket. The OOD guard's training statistics are
monkeypatched rather than loaded from ``backend/artifacts/`` so this suite does not depend on the
(large, binary) real artefact being present in every environment that runs it.
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
from app.domain.montage import MONTAGE
from app.domain.participants import AffectedSide, AgeBand, Sex, new_participant
from app.main import app
from app.routers import calibrations as calibrations_module
from tests.fakes import FakeDocumentStore

CLINICIAN_A = CurrentUser(uid="clinician-a", email="a@clinic.example", role="clinician")
CLINICIAN_B = CurrentUser(uid="clinician-b", email="b@clinic.example", role="clinician")

RNG = np.random.default_rng(1234)


def _object(kind: str, participant_id: str, token: str, uid: str = "clinician-a") -> str:
    """An object name in the shape ``storage.new_object_name`` now mints.

    The owning clinician's uid and the participant id are both path segments, and both are
    checked by ``verify_upload_object`` when the object is registered -- so a test that names an
    object has to name one that could actually have been minted for that caller.
    """
    return f"{kind}/{uid}/{participant_id}/{token}.csv"


class FakeObjectStore:
    """In-memory ``ObjectStore``: ``read_bytes`` serves whatever ``put`` was given."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, object_name: str, data: bytes) -> None:
        self._objects[object_name] = data

    def signed_upload_url(self, object_name: str, content_type: str) -> str:
        return f"https://fake-bucket.example/{object_name}"

    def read_bytes(self, object_name: str) -> bytes:
        return self._objects[object_name]

    def size_bytes(self, object_name: str) -> int | None:
        """Mirrors GcsObjectStore: ``None`` when the object is absent, rather than raising."""
        blob = self._objects.get(object_name)
        return None if blob is None else len(blob)


def _synthetic_calibration_csv(*, sufficient_tasks: tuple[str, ...] = ("DNS", "STDUP")) -> bytes:
    """A calibration CSV with enough contiguous, same-label blocks that every task in
    ``sufficient_tasks`` clears the default sufficiency thresholds (20 windows, 3 blocks), and
    exactly one block -- too short to yield any window -- for a task left deliberately
    under-calibrated ("UPS"), so sufficiency tests have something to contrast against."""
    block_samples = 480 * 8  # 14 windows/block at the default 480/240 window/step
    rows: list[pd.DataFrame] = []
    # Interleaved across tasks (DNS, STDUP, DNS, STDUP, ...) rather than grouped, because
    # parse_calibration_csv splits on a *label change*: three consecutive same-label blocks
    # would be indistinguishable from one long one and collapse into a single block.
    for _ in range(3):  # 3 blocks per task clears min_calibration_blocks
        for task in sufficient_tasks:
            signal = RNG.normal(loc=0.0, scale=50.0, size=(block_samples, len(MONTAGE)))
            block = pd.DataFrame(signal, columns=list(MONTAGE))
            block["label"] = task
            rows.append(block)
    # "UPS": one short block, too short to produce a single window.
    short_signal = RNG.normal(loc=0.0, scale=50.0, size=(100, len(MONTAGE)))
    short_block = pd.DataFrame(short_signal, columns=list(MONTAGE))
    short_block["label"] = "UPS"
    rows.append(short_block)

    frame = pd.concat(rows, ignore_index=True)
    frame.insert(0, "Time", np.arange(len(frame)) / 1920.0)
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue()


def _neutral_ood_stats() -> tuple[np.ndarray, np.ndarray]:
    """Mean 0 / identity covariance: a z-scored capture's distance lands well under the
    default 12.0 threshold, so tests using this fixture exercise the "not flagged" path."""
    return np.zeros(72), np.eye(72)


def _adversarial_ood_stats() -> tuple[np.ndarray, np.ndarray]:
    """A training mean placed far from anything a z-scored capture could produce, so the
    resulting distance is guaranteed to clear the 12.0 threshold."""
    return np.full(72, 1000.0), np.eye(72)


def _client_as(
    user: CurrentUser,
    store: FakeDocumentStore,
    objects: FakeObjectStore,
) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_document_store] = lambda: store
    app.dependency_overrides[get_object_store] = lambda: objects
    return TestClient(app)


def _reset():
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _neutral_ood(monkeypatch: pytest.MonkeyPatch):
    """Every test gets the neutral (not-flagged) OOD stats unless it overrides this itself."""
    monkeypatch.setattr(
        calibrations_module, "get_ood_stats", lambda _artefact_dir: _neutral_ood_stats()
    )
    yield


def test_create_requires_authentication():
    _reset()
    response = TestClient(app).post(
        "/v1/calibrations",
        json={"participant_id": "p1", "object_name": _object("calibration", "p1", "x")},
    )
    assert response.status_code == 401
    _reset()


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


def test_create_rejects_a_participant_that_is_not_the_caller_s():
    store = FakeDocumentStore()
    participant_id = _register_participant(store, owner="someone-else")
    objects = FakeObjectStore()
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "x"),
        },
    )

    assert response.status_code == 404
    _reset()


def test_create_reports_per_task_sufficiency_and_persists_a_calibration_record():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put(_object("calibration", participant_id, "one"), _synthetic_calibration_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "one"),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["active"] is True
    assert body["ood_flag"] is False
    assert body["per_task"]["DNS"]["status"] == "calibrated"
    assert body["per_task"]["DNS"]["sufficient"] is True
    assert body["per_task"]["STDUP"]["sufficient"] is True
    # "UPS" only had one too-short block: no windows at all, so it is unattempted rather than
    # merely insufficient -- a block that produced zero windows never touched the counts.
    assert body["per_task"]["UPS"]["status"] == "not_attempted"
    assert body["per_task"]["WAK"]["status"] == "not_attempted"
    assert len(body["envelope_peak"]) == 9

    stored = store.get(COLLECTIONS.CALIBRATIONS, body["id"])
    assert stored is not None
    assert stored["participantId"] == participant_id
    _reset()


def test_create_rejects_a_non_conformant_capture_c1():
    """C1: a calibration capture that doesn't match the montage contract is refused with 409,
    MONTAGE_REJECTED, naming every violating field -- the same refusal D3 uses for a session
    upload, since it is the same failure class (see SRS §4.2 C1)."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    bad_csv = _synthetic_calibration_csv().replace(b"sEMG: soleus", b"sEMG: not-a-channel")
    objects.put(_object("calibration", participant_id, "bad"), bad_csv)
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "bad"),
        },
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "montage_rejected"
    assert body["details"]  # names the violating field(s)
    _reset()


def test_create_rejects_a_capture_missing_the_label_column_c1():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    csv_without_label = _synthetic_calibration_csv().replace(b",label", b",not_label")
    objects.put(_object("calibration", participant_id, "no-label"), csv_without_label)
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "no-label"),
        },
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "montage_rejected"
    assert any(v.get("reason") == "missing_label_column" for v in body["details"])
    _reset()


def test_create_writes_an_audit_entry():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put(_object("calibration", participant_id, "one"), _synthetic_calibration_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "one"),
        },
    )
    assert response.status_code == 201

    audit_entries = store.query(COLLECTIONS.AUDIT, targetId=response.json()["id"])
    assert len(audit_entries) == 1
    assert audit_entries[0]["action"] == "calibration.create"
    _reset()


def test_recalibration_supersedes_the_previous_active_record_c5():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put(_object("calibration", participant_id, "one"), _synthetic_calibration_csv())
    objects.put(_object("calibration", participant_id, "two"), _synthetic_calibration_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    first = client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "one"),
        },
    ).json()
    second = client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "two"),
        },
    ).json()

    assert first["version"] == 1
    assert second["version"] == 2

    first_stored = store.get(COLLECTIONS.CALIBRATIONS, first["id"])
    assert first_stored is not None
    assert first_stored["active"] is False  # superseded, not deleted (C5)
    second_stored = store.get(COLLECTIONS.CALIBRATIONS, second["id"])
    assert second_stored is not None
    assert second_stored["active"] is True
    _reset()


def test_out_of_distribution_capture_is_refused_but_retained_c4(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        calibrations_module, "get_ood_stats", lambda _artefact_dir: _adversarial_ood_stats()
    )
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put(_object("calibration", participant_id, "one"), _synthetic_calibration_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "one"),
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "out_of_distribution"

    # The record was still persisted -- errors.OutOfDistribution's own docstring promises this.
    active = store.query(COLLECTIONS.CALIBRATIONS, participantId=participant_id, active=True)
    assert len(active) == 1
    assert active[0]["oodFlag"] is True
    _reset()


def test_get_active_calibration_returns_not_calibrated_when_none_exists():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.get(f"/v1/participants/{participant_id}/calibration/active")

    assert response.status_code == 412
    assert response.json()["code"] == "not_calibrated"
    _reset()


def test_get_active_calibration_returns_the_current_version():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put(_object("calibration", participant_id, "one"), _synthetic_calibration_csv())
    objects.put(_object("calibration", participant_id, "two"), _synthetic_calibration_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "one"),
        },
    )
    client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "two"),
        },
    )

    response = client.get(f"/v1/participants/{participant_id}/calibration/active")

    assert response.status_code == 200
    assert response.json()["version"] == 2
    _reset()


def test_a_clinician_cannot_read_another_clinician_s_calibration():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store, owner="clinician-a")
    objects.put(_object("calibration", participant_id, "one"), _synthetic_calibration_csv())
    owner_client = _client_as(CLINICIAN_A, store, objects)
    owner_client.post(
        "/v1/calibrations",
        json={
            "participant_id": participant_id,
            "object_name": _object("calibration", participant_id, "one"),
        },
    )

    other_client = _client_as(CLINICIAN_B, store, objects)
    response = other_client.get(f"/v1/participants/{participant_id}/calibration/active")

    assert response.status_code == 404
    _reset()
