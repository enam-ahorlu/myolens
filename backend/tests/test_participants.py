"""Participant records (SRS §4.2 B): pseudonymous creation (B1), ownership-scoped list/view/edit/
soft-delete (A3, B2), and an audit entry per mutation (E8)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.firestore_repo import COLLECTIONS, get_document_store
from app.auth import CurrentUser, get_current_user
from app.main import app
from tests.fakes import FakeDocumentStore

CLINICIAN_A = CurrentUser(uid="clinician-a", email="a@clinic.example", role="clinician")
CLINICIAN_B = CurrentUser(uid="clinician-b", email="b@clinic.example", role="clinician")
ADMIN = CurrentUser(uid="admin-1", email="admin@clinic.example", role="admin")

VALID_PAYLOAD = {
    "code": "P-001",
    "age_band": "30_44",
    "sex": "female",
    "affected_side": "left",
    "notes": "post-op review",
}


def _client_as(user: CurrentUser, store: FakeDocumentStore) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_document_store] = lambda: store
    return TestClient(app)


def _reset():
    app.dependency_overrides.clear()


def test_create_requires_authentication():
    _reset()
    response = TestClient(app).post("/v1/participants", json=VALID_PAYLOAD)
    assert response.status_code == 401
    _reset()


def test_create_returns_the_participant_with_no_name_field_anywhere():
    store = FakeDocumentStore()
    client = _client_as(CLINICIAN_A, store)

    response = client.post("/v1/participants", json=VALID_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "P-001"
    assert body["created_by"] == "clinician-a"
    assert "name" not in body
    _reset()


def test_create_rejects_a_code_that_looks_like_a_name():
    store = FakeDocumentStore()
    client = _client_as(CLINICIAN_A, store)

    response = client.post("/v1/participants", json={**VALID_PAYLOAD, "code": "Jane Doe"})

    assert response.status_code == 422
    _reset()


def test_create_writes_an_audit_entry():
    store = FakeDocumentStore()
    client = _client_as(CLINICIAN_A, store)

    created = client.post("/v1/participants", json=VALID_PAYLOAD).json()

    entries = store.query(COLLECTIONS.AUDIT, targetId=created["id"])
    assert len(entries) == 1
    assert entries[0]["action"] == "participant.create"
    assert entries[0]["actor"] == "clinician-a"
    assert entries[0]["before"] is None
    assert entries[0]["after"]["code"] == "P-001"
    _reset()


def test_clinicians_see_only_their_own_participants():
    """A3's literal acceptance test."""
    store = FakeDocumentStore()
    _client_as(CLINICIAN_A, store).post("/v1/participants", json=VALID_PAYLOAD)
    _client_as(CLINICIAN_B, store).post("/v1/participants", json={**VALID_PAYLOAD, "code": "P-002"})

    a_sees = _client_as(CLINICIAN_A, store).get("/v1/participants").json()
    b_sees = _client_as(CLINICIAN_B, store).get("/v1/participants").json()

    assert [p["code"] for p in a_sees] == ["P-001"]
    assert [p["code"] for p in b_sees] == ["P-002"]
    _reset()


def test_admin_sees_every_clinicians_participants():
    store = FakeDocumentStore()
    _client_as(CLINICIAN_A, store).post("/v1/participants", json=VALID_PAYLOAD)
    _client_as(CLINICIAN_B, store).post("/v1/participants", json={**VALID_PAYLOAD, "code": "P-002"})

    admin_sees = _client_as(ADMIN, store).get("/v1/participants").json()

    assert {p["code"] for p in admin_sees} == {"P-001", "P-002"}
    _reset()


def test_cross_clinician_read_is_404_not_403():
    """A3's rules-test intent, restated at the API: a non-owner gets the same response as a
    nonexistent id, so a probing request cannot learn that a given id belongs to someone else
    (the same reasoning ADR-004 applies to unauthenticated callers)."""
    store = FakeDocumentStore()
    created = _client_as(CLINICIAN_A, store).post("/v1/participants", json=VALID_PAYLOAD).json()

    response = _client_as(CLINICIAN_B, store).get(f"/v1/participants/{created['id']}")

    assert response.status_code == 404
    _reset()


def test_owner_can_view_their_own_participant():
    store = FakeDocumentStore()
    created = _client_as(CLINICIAN_A, store).post("/v1/participants", json=VALID_PAYLOAD).json()

    response = _client_as(CLINICIAN_A, store).get(f"/v1/participants/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    _reset()


def test_viewing_a_nonexistent_participant_is_404():
    store = FakeDocumentStore()
    response = _client_as(CLINICIAN_A, store).get("/v1/participants/does-not-exist")
    assert response.status_code == 404
    _reset()


def test_edit_changes_only_the_supplied_fields_and_audits_before_and_after():
    store = FakeDocumentStore()
    client = _client_as(CLINICIAN_A, store)
    created = client.post("/v1/participants", json=VALID_PAYLOAD).json()

    response = client.patch(f"/v1/participants/{created['id']}", json={"notes": "updated note"})

    assert response.status_code == 200
    body = response.json()
    assert body["notes"] == "updated note"
    assert body["code"] == "P-001"  # untouched

    entries = store.query(COLLECTIONS.AUDIT, targetId=created["id"])
    edit_entries = [e for e in entries if e["action"] == "participant.update"]
    assert len(edit_entries) == 1
    assert edit_entries[0]["before"]["notes"] == "post-op review"
    assert edit_entries[0]["after"]["notes"] == "updated note"
    _reset()


def test_a_non_owner_cannot_edit_someone_elses_participant():
    store = FakeDocumentStore()
    created = _client_as(CLINICIAN_A, store).post("/v1/participants", json=VALID_PAYLOAD).json()

    response = _client_as(CLINICIAN_B, store).patch(
        f"/v1/participants/{created['id']}", json={"notes": "tampered"}
    )

    assert response.status_code == 404
    _reset()


def test_soft_delete_hides_from_the_list_but_keeps_the_record():
    """B2: 'Soft-delete hides from the list and retains the audit trail'."""
    store = FakeDocumentStore()
    client = _client_as(CLINICIAN_A, store)
    created = client.post("/v1/participants", json=VALID_PAYLOAD).json()

    delete_response = client.delete(f"/v1/participants/{created['id']}")
    assert delete_response.status_code == 200

    listed = client.get("/v1/participants").json()
    assert listed == []

    get_response = client.get(f"/v1/participants/{created['id']}")
    assert get_response.status_code == 404

    # The record itself still exists in the store, deletedAt set, not destroyed.
    raw = store.get(COLLECTIONS.PARTICIPANTS, created["id"])
    assert raw is not None
    assert raw["deletedAt"] is not None

    entries = store.query(COLLECTIONS.AUDIT, targetId=created["id"])
    assert any(e["action"] == "participant.delete" for e in entries)
    _reset()


def test_edit_rejects_a_code_that_looks_like_a_name():
    store = FakeDocumentStore()
    client = _client_as(CLINICIAN_A, store)
    created = client.post("/v1/participants", json=VALID_PAYLOAD).json()

    response = client.patch(f"/v1/participants/{created['id']}", json={"code": "Jane Doe"})

    assert response.status_code == 422
    _reset()
