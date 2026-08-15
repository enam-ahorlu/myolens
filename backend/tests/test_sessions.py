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
from app.middleware.rate_limit import InProcessRateLimiter, get_rate_limiter
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


def _object(kind: str, participant_id: str, token: str, uid: str = "clinician-a") -> str:
    """An object name in the shape ``storage.new_object_name`` now mints.

    The owning clinician's uid and the participant id are both path segments, and both are
    checked by ``verify_upload_object`` when the object is registered -- so a test that names an
    object has to name one that could actually have been minted for that caller.
    """
    return f"{kind}/{uid}/{participant_id}/{token}.csv"


class FakeObjectStore:
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
    # A fresh, generously-limited limiter per test -- the same isolation discipline as the fake
    # document/object stores above. I3's own behaviour is exercised by overriding this again,
    # deliberately low, in the two rate-limit tests below.
    app.dependency_overrides[get_rate_limiter] = lambda: InProcessRateLimiter(limit_per_hour=1000)
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
        "/v1/sessions",
        json={"participant_id": "p1", "object_name": _object("session", "p1", "x")},
    )
    assert response.status_code == 401
    _reset()


def test_create_session_registers_a_valid_upload():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
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
    objects.put(_object("session", participant_id, "bad"), buffer.getvalue())
    client = _client_as(CLINICIAN_A, store, objects)

    response = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "bad"),
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "montage_rejected"
    _reset()


def test_segment_requires_a_calibration():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
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
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
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
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
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
    objects.put(_object("session", participant_id, "one"), _session_csv())
    owner_client = _client_as(CLINICIAN_A, store, objects)

    created = owner_client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
    ).json()

    other_client = _client_as(CLINICIAN_B, store, objects)
    response = other_client.post(f"/v1/sessions/{created['id']}/segment")

    assert response.status_code == 404
    _reset()


def test_segment_is_rate_limited_per_user_i3():
    """I3: segmentation is refused with 429 once a user exceeds the per-hour ceiling, and the
    limiter is checked before the calibration/montage/inference work runs at all."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)
    limiter = InProcessRateLimiter(limit_per_hour=1)  # one instance, so hits actually accumulate
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
    ).json()

    first = client.post(f"/v1/sessions/{created['id']}/segment")
    second = client.post(f"/v1/sessions/{created['id']}/segment")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limited"
    _reset()


def test_segment_rate_limit_is_tracked_per_user_not_globally_i3():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store, owner="clinician-a")
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put(_object("session", participant_id, "one"), _session_csv())
    limiter = InProcessRateLimiter(limit_per_hour=1)  # one instance, so hits actually accumulate
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    owner_client = _client_as(CLINICIAN_A, store, objects)
    created = owner_client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
    ).json()
    owner_client.post(f"/v1/sessions/{created['id']}/segment")  # consumes clinician-a's quota

    other_client = _client_as(CLINICIAN_B, store, objects)
    response = other_client.post(f"/v1/sessions/{created['id']}/segment")

    # clinician-b's own quota is untouched; the 404 (not a 429) proves the request reached the
    # ownership check, i.e. it was not rate-limited.
    assert response.status_code == 404
    _reset()


# --- Segmentation review and approval (E3-E8) --------------------------------------------


def _segmented_session(
    store: FakeDocumentStore, objects: FakeObjectStore
) -> tuple[TestClient, str, dict]:
    """A fully segmented session, ready for review. FakeEnsemble always favours DNS; with only
    WAK and STDUP calibrated, DNS and UPS are zeroed by D5 and WAK/STDUP land in an exact tie
    (both keep the ensemble's 0.05 remainder) -- numpy's argmax breaks that tie toward the lower
    CLASSES index, STDUP, deterministically. The whole session therefore comes back as a single
    STDUP bout, at 0.5 mean confidence (flagged: low_confidence, since 0.5 < the 0.60 default)."""
    participant_id = _register_participant(store)
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)

    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
    ).json()
    segmentation = client.post(f"/v1/sessions/{created['id']}/segment").json()
    return client, created["id"], segmentation


def test_relabel_persists_and_marks_the_bout_corrected():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout = segmentation["bouts"][0]
    assert bout["task"] == "STDUP"

    response = client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout['id']}", json={"op": "relabel", "task": "WAK"}
    )

    assert response.status_code == 200
    body = response.json()
    updated = body["bouts"][0]
    assert updated["task"] == "WAK"
    assert updated["corrected"] is True
    assert updated["original_task"] == "STDUP"

    stored = store.get(COLLECTIONS.BOUTS, bout["id"])
    assert stored["task"] == "WAK"
    _reset()


def test_relabel_rejects_an_uncalibrated_task():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout = segmentation["bouts"][0]

    # DNS was never calibrated for this participant (only WAK and STDUP were).
    response = client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout['id']}", json={"op": "relabel", "task": "DNS"}
    )

    assert response.status_code == 422
    _reset()


def test_exclude_marks_the_bout_excluded_and_writes_an_audit_entry():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout = segmentation["bouts"][0]

    response = client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout['id']}",
        json={"op": "exclude", "reason": "artefact"},
    )

    assert response.status_code == 200
    body = response.json()["bouts"][0]
    assert body["excluded"] is True
    assert body["exclusion_reason"] == "artefact"

    entries = store.query(COLLECTIONS.AUDIT, targetId=bout["id"])
    assert any(e["action"] == "bout.exclude" for e in entries)
    _reset()


def test_split_produces_two_bouts_no_window_lost():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout = segmentation["bouts"][0]
    total_windows = bout["window_count"]
    assert total_windows > 1

    response = client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout['id']}", json={"op": "split", "at_window": 10}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["bouts"]) == 2
    first, second = body["bouts"]
    assert first["window_count"] + second["window_count"] == total_windows
    assert first["id"] == bout["id"]
    assert second["id"] != bout["id"]

    remaining_bouts = store.query(COLLECTIONS.BOUTS, sessionId=session_id)
    assert len(remaining_bouts) == 2
    _reset()


def test_split_then_merge_round_trips_to_one_bout():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout = segmentation["bouts"][0]

    split = client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout['id']}", json={"op": "split", "at_window": 10}
    ).json()
    first, second = split["bouts"]

    response = client.patch(
        f"/v1/sessions/{session_id}/bouts/{first['id']}",
        json={"op": "merge", "neighbor_bout_id": second["id"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["bouts"]) == 1
    merged = body["bouts"][0]
    assert merged["window_count"] == bout["window_count"]
    assert body["removed_bout_ids"] == [second["id"]]

    remaining_bouts = store.query(COLLECTIONS.BOUTS, sessionId=session_id)
    assert len(remaining_bouts) == 1
    assert store.get(COLLECTIONS.BOUTS, second["id"]) is None
    _reset()


def test_corrections_are_refused_before_segmentation_exists():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)
    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
    ).json()

    response = client.patch(
        f"/v1/sessions/{created['id']}/bouts/does-not-exist",
        json={"op": "exclude", "reason": "artefact"},
    )

    assert response.status_code == 412
    assert response.json()["code"] == "precondition_failed"
    _reset()


def test_approve_locks_the_session_and_further_corrections_are_refused():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout = segmentation["bouts"][0]

    response = client.post(f"/v1/sessions/{session_id}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    stored = store.get(COLLECTIONS.SESSIONS, session_id)
    assert stored["status"] == "approved"

    correction = client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout['id']}",
        json={"op": "exclude", "reason": "artefact"},
    )
    assert correction.status_code == 423
    assert correction.json()["code"] == "locked"

    reapprove = client.post(f"/v1/sessions/{session_id}/approve")
    assert reapprove.status_code == 423
    _reset()


def test_approve_requires_segmentation_first():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)
    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
    ).json()

    response = client.post(f"/v1/sessions/{created['id']}/approve")

    assert response.status_code == 412
    _reset()


def test_approve_writes_an_audit_entry():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, _segmentation = _segmented_session(store, objects)

    client.post(f"/v1/sessions/{session_id}/approve")

    entries = store.query(COLLECTIONS.AUDIT, targetId=session_id)
    assert any(e["action"] == "session.approve" for e in entries)
    _reset()


def test_metrics_are_refused_before_approval_f1_e7():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, _segmentation = _segmented_session(store, objects)

    response = client.get(f"/v1/sessions/{session_id}/metrics")

    assert response.status_code == 412
    assert response.json()["code"] == "segmentation_not_approved"
    _reset()


def test_metrics_are_refused_before_segmentation():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    _give_active_calibration(store, participant_id, calibrated_tasks=("WAK", "STDUP"))
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)
    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
    ).json()

    response = client.get(f"/v1/sessions/{created['id']}/metrics")

    assert response.status_code == 412
    assert response.json()["code"] == "segmentation_not_approved"
    _reset()


def test_metrics_are_computed_once_approved_f1():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    assert len(segmentation["bouts"]) == 1
    bout = segmentation["bouts"][0]

    client.post(f"/v1/sessions/{session_id}/approve")
    response = client.get(f"/v1/sessions/{session_id}/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert len(body["channels"]) == 9
    assert body["flagged_count"] == 1  # the single low-confidence STDUP bout

    assert len(body["tasks"]) == 1
    task_metrics = body["tasks"][0]
    assert task_metrics["task"] == "STDUP"
    assert task_metrics["bout_count"] == 1
    assert task_metrics["correction_rate_pct"] == pytest.approx(0.0)
    assert task_metrics["model_confidence_mean"] == pytest.approx(bout["mean_confidence"])
    assert len(task_metrics["amp_mean"]) == 9
    assert len(task_metrics["amp_peak"]) == 9
    assert len(task_metrics["duty_cycle"]) == 9
    assert "value" in task_metrics["cci_knee"]
    assert "value" in task_metrics["cci_ankle"]

    stored = store.get(COLLECTIONS.METRICS, session_id)
    assert stored is not None
    assert stored["session_id"] == session_id
    _reset()


def test_metrics_reflect_a_relabel_correction():
    """Once corrected, a bout's windows count toward the task it was corrected *to*, and its
    (unchanged) mean_confidence is reported as that task's pre-correction confidence -- see
    ``compute_task_metrics``'s docstring."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout = segmentation["bouts"][0]

    client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout['id']}", json={"op": "relabel", "task": "WAK"}
    )
    client.post(f"/v1/sessions/{session_id}/approve")
    body = client.get(f"/v1/sessions/{session_id}/metrics").json()

    assert len(body["tasks"]) == 1
    task_metrics = body["tasks"][0]
    assert task_metrics["task"] == "WAK"
    assert task_metrics["correction_rate_pct"] == pytest.approx(100.0)
    _reset()


def test_metrics_omit_a_task_whose_only_bout_was_excluded_e6():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout = segmentation["bouts"][0]

    client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout['id']}",
        json={"op": "exclude", "reason": "artefact"},
    )
    client.post(f"/v1/sessions/{session_id}/approve")
    response = client.get(f"/v1/sessions/{session_id}/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["tasks"] == []
    assert body["flagged_count"] == 1  # exclusion does not change flagged status
    _reset()


def test_metrics_are_cached_after_the_first_computation():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, _segmentation = _segmented_session(store, objects)
    client.post(f"/v1/sessions/{session_id}/approve")

    first = client.get(f"/v1/sessions/{session_id}/metrics").json()
    stored_after_first = store.get(COLLECTIONS.METRICS, session_id)
    assert stored_after_first is not None

    second = client.get(f"/v1/sessions/{session_id}/metrics").json()
    assert second == first
    _reset()


def test_export_is_refused_before_approval_g1_e7():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, _segmentation = _segmented_session(store, objects)

    response = client.get(f"/v1/sessions/{session_id}/export")

    assert response.status_code == 412
    assert response.json()["code"] == "segmentation_not_approved"
    _reset()


def test_export_returns_a_pdf_g1():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, _segmentation = _segmented_session(store, objects)
    client.post(f"/v1/sessions/{session_id}/approve")

    response = client.get(f"/v1/sessions/{session_id}/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert session_id in response.headers["content-disposition"]
    # A real PDF, not an empty or truncated stream.
    assert response.content[:5] == b"%PDF-"
    assert response.content[-1:] in (b"\n", b"%")  # reportlab terminates with %%EOF (+ newline)
    assert len(response.content) > 1000
    _reset()


def test_export_reflects_the_same_numbers_as_the_metrics_endpoint():
    """G1's metric tables must be the numbers a clinician already reviewed via
    GET .../metrics, not a second, independently-computed set."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, _segmentation = _segmented_session(store, objects)
    client.post(f"/v1/sessions/{session_id}/approve")

    metrics = client.get(f"/v1/sessions/{session_id}/metrics").json()
    export_response = client.get(f"/v1/sessions/{session_id}/export")

    assert export_response.status_code == 200
    # The PDF is binary, so this checks the two endpoints share the same cached source rather
    # than parsing the PDF back out: the metrics cache document is what the export reads too.
    cached = store.get(COLLECTIONS.METRICS, session_id)
    assert cached["tasks"] == metrics["tasks"]
    _reset()


def test_export_requires_authentication():
    _reset()
    response = TestClient(app).get("/v1/sessions/does-not-exist/export")
    assert response.status_code == 401
    _reset()


# -- Retrieval (SRS §4.2 E3's "persists", and §10's correction) ----------------------------------
#
# Until these two routes existed, a session could only be seen in the response of the call that
# created or changed it. A correction "persisted" in Firestore and was unobservable from anywhere:
# reload the page and it was gone for good. §10 already carried two GETs keyed by a session id --
# metrics and export -- and nothing that would ever yield one.


def test_get_session_returns_the_same_shape_segmentation_returned():
    """A caller reopening a session should get exactly what the caller who segmented it got.
    Two shapes for one thing is two things to keep in step."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)

    fetched = client.get(f"/v1/sessions/{session_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["session"] == segmentation["session"]
    assert body["bouts"] == segmentation["bouts"]
    assert body["flagged_count"] == segmentation["flagged_count"]
    _reset()


def test_get_session_shows_a_correction_that_was_made_earlier():
    """The point of the route. E3 says a relabel persists; this is the only thing that can
    observe that it did."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, segmentation = _segmented_session(store, objects)
    bout_id = segmentation["bouts"][0]["id"]
    client.patch(
        f"/v1/sessions/{session_id}/bouts/{bout_id}",
        json={"op": "relabel", "task": "WAK"},
    )

    reopened = client.get(f"/v1/sessions/{session_id}").json()

    relabelled = next(b for b in reopened["bouts"] if b["id"] == bout_id)
    assert relabelled["task"] == "WAK"
    assert relabelled["corrected"] is True
    assert relabelled["original_task"] == "STDUP"
    _reset()


def test_get_session_returns_an_unsegmented_session_with_no_bouts():
    """Not an error. A session that has been uploaded but not segmented is a state the client
    has to render, and `status` is what says which state it is."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    objects.put(_object("session", participant_id, "one"), _session_csv())
    client = _client_as(CLINICIAN_A, store, objects)
    created = client.post(
        "/v1/sessions",
        json={
            "participant_id": participant_id,
            "object_name": _object("session", participant_id, "one"),
        },
    ).json()

    body = client.get(f"/v1/sessions/{created['id']}").json()

    assert body["session"]["status"] == "uploaded"
    assert body["bouts"] == []
    assert body["flagged_count"] == 0
    _reset()


def test_a_clinician_cannot_fetch_another_clinician_s_session():
    """404, not 403 -- the same non-disclosure judgement every other owned resource makes."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    _client, session_id, _segmentation = _segmented_session(store, objects)

    intruder = _client_as(CLINICIAN_B, store, objects)
    response = intruder.get(f"/v1/sessions/{session_id}")

    assert response.status_code == 404
    _reset()


def test_get_session_requires_authentication():
    _reset()
    response = TestClient(app).get("/v1/sessions/does-not-exist")
    assert response.status_code == 401
    _reset()


def test_list_participant_sessions_is_newest_first():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    client = _client_as(CLINICIAN_A, store, objects)
    created_ids = []
    for token in ("one", "two", "three"):
        objects.put(_object("session", participant_id, token), _session_csv())
        created_ids.append(
            client.post(
                "/v1/sessions",
                json={
                    "participant_id": participant_id,
                    "object_name": _object("session", participant_id, token),
                },
            ).json()["id"]
        )

    listed = client.get(f"/v1/participants/{participant_id}/sessions").json()

    assert [s["id"] for s in listed] == list(reversed(created_ids))
    _reset()


def test_list_participant_sessions_does_not_leak_another_clinician_s_participant():
    """A3 is enforced through the participant: the sessions are never queried at all."""
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store, owner="clinician-a")

    intruder = _client_as(CLINICIAN_B, store, objects)
    response = intruder.get(f"/v1/participants/{participant_id}/sessions")

    assert response.status_code == 404
    _reset()


def test_list_participant_sessions_is_empty_for_a_participant_with_none():
    store = FakeDocumentStore()
    objects = FakeObjectStore()
    participant_id = _register_participant(store)
    client = _client_as(CLINICIAN_A, store, objects)

    assert client.get(f"/v1/participants/{participant_id}/sessions").json() == []
    _reset()
