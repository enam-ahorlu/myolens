"""Admin: list clinicians and set roles (A4, SRS §4.2 A).

``firebase_auth`` is patched at the call site inside ``app.routers.admin``, the same discipline
``test_auth.py`` uses for ``verify_id_token`` -- these tests exercise MyoLens's own routing and
authorisation logic, never a real Firebase project.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from firebase_admin import auth as firebase_auth

from app.auth import CurrentUser, get_current_user
from app.main import app
from app.routers import admin as admin_module

ADMIN = CurrentUser(uid="admin-1", email="admin@clinic.example", role="admin")
CLINICIAN = CurrentUser(uid="clinician-1", email="c@clinic.example", role="clinician")


@dataclass
class FakeUserRecord:
    uid: str
    email: str | None
    disabled: bool = False
    custom_claims: dict | None = field(default_factory=dict)


class FakeListUsersPage:
    def __init__(self, users: list[FakeUserRecord]) -> None:
        self._users = users

    def iterate_all(self):
        return iter(self._users)


def _client_as(user: CurrentUser) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _reset():
    app.dependency_overrides.clear()


def test_listing_clinicians_requires_authentication():
    _reset()
    response = TestClient(app).get("/v1/admin/clinicians")
    assert response.status_code == 401
    _reset()


def test_a_clinician_cannot_list_clinicians():
    client = _client_as(CLINICIAN)
    response = client.get("/v1/admin/clinicians")
    assert response.status_code == 403
    _reset()


def test_admin_lists_every_account_with_its_role(monkeypatch: pytest.MonkeyPatch):
    users = [
        FakeUserRecord(uid="u1", email="a@clinic.example", custom_claims={"role": "admin"}),
        FakeUserRecord(uid="u2", email="b@clinic.example", custom_claims={"role": "clinician"}),
        # No custom claim yet: defaults to clinician, same as get_current_user's own default.
        FakeUserRecord(uid="u3", email="c@clinic.example", custom_claims=None),
    ]
    monkeypatch.setattr(admin_module.firebase_auth, "list_users", lambda: FakeListUsersPage(users))
    client = _client_as(ADMIN)

    response = client.get("/v1/admin/clinicians")

    assert response.status_code == 200
    body = {u["uid"]: u for u in response.json()}
    assert body["u1"]["role"] == "admin"
    assert body["u2"]["role"] == "clinician"
    assert body["u3"]["role"] == "clinician"
    _reset()


def test_setting_a_role_requires_admin():
    client = _client_as(CLINICIAN)
    response = client.patch("/v1/admin/clinicians/u2/role", json={"role": "admin"})
    assert response.status_code == 403
    _reset()


def test_admin_sets_a_clinician_s_role(monkeypatch: pytest.MonkeyPatch):
    record = FakeUserRecord(uid="u2", email="b@clinic.example", custom_claims={"role": "clinician"})
    calls: list[tuple[str, dict]] = []

    def fake_get_user(uid: str):
        if uid != "u2":
            raise firebase_auth.UserNotFoundError("no such user")
        return record

    def fake_set_custom_user_claims(uid: str, claims: dict) -> None:
        calls.append((uid, claims))
        record.custom_claims = claims

    monkeypatch.setattr(admin_module.firebase_auth, "get_user", fake_get_user)
    monkeypatch.setattr(
        admin_module.firebase_auth, "set_custom_user_claims", fake_set_custom_user_claims
    )
    client = _client_as(ADMIN)

    response = client.patch("/v1/admin/clinicians/u2/role", json={"role": "admin"})

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert calls == [("u2", {"role": "admin"})]
    _reset()


def test_setting_a_role_for_an_unknown_user_is_404(monkeypatch: pytest.MonkeyPatch):
    def fake_get_user(uid: str):
        raise firebase_auth.UserNotFoundError("no such user")

    monkeypatch.setattr(admin_module.firebase_auth, "get_user", fake_get_user)
    client = _client_as(ADMIN)

    response = client.patch("/v1/admin/clinicians/ghost/role", json={"role": "admin"})

    assert response.status_code == 404
    _reset()
