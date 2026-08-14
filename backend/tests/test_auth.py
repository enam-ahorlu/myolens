"""Firebase ID-token verification (ADR-004, I2, A1, A2).

These tests never talk to a real Firebase project — ``firebase_auth.verify_id_token`` is patched
at the call site. What is under test is MyoLens's own logic: which exceptions become which error
code, what an absent claim defaults to, and how the two dependencies compose.

A tiny FastAPI app with two throwaway routes stands in for a production route. The eleven frozen
API-surface routes (§10 of the plan of record) do not exist yet; this suite is what they will be
built on, not a substitute for testing them once they do.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from firebase_admin import auth as firebase_auth

from app.auth import CurrentUser, get_current_user, require_role
from app.errors import MyoLensError

auth_test_app = FastAPI()


@auth_test_app.exception_handler(MyoLensError)
async def _handle_refusal(request: Request, exc: MyoLensError) -> JSONResponse:
    # Mirrors app.main's handler so this suite exercises the same envelope shape a real route
    # would return, without pulling in the full app (and its ONNX artefacts) just to test auth.
    return JSONResponse(status_code=exc.status_code, content=exc.envelope().model_dump(mode="json"))


@auth_test_app.get("/protected")
def protected_route(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"uid": user.uid, "role": user.role}


@auth_test_app.get("/admin-only")
def admin_route(user: CurrentUser = Depends(require_role("admin"))) -> dict:
    return {"uid": user.uid}


client = TestClient(auth_test_app)


def _bearer(token: str = "irrelevant-in-tests") -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_missing_bearer_token_is_401_unauthenticated():
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


def test_empty_bearer_token_is_401():
    response = client.get("/protected", headers={"Authorization": "Bearer "})
    assert response.status_code == 401


@patch("app.auth._firebase_app")
@patch("app.auth.firebase_auth.verify_id_token")
def test_valid_token_reaches_the_handler(mock_verify, mock_app):
    mock_verify.return_value = {"uid": "clinician-1", "email": "a@b.com", "role": "clinician"}
    response = client.get("/protected", headers=_bearer())
    assert response.status_code == 200
    assert response.json() == {"uid": "clinician-1", "role": "clinician"}


@patch("app.auth._firebase_app")
@patch("app.auth.firebase_auth.verify_id_token")
def test_missing_role_claim_defaults_to_clinician(mock_verify, mock_app):
    """A4: an account is a clinician until an admin sets otherwise. Never silently admin."""
    mock_verify.return_value = {"uid": "no-claim-1", "email": None}
    response = client.get("/protected", headers=_bearer())
    assert response.json()["role"] == "clinician"


@patch("app.auth._firebase_app")
@patch("app.auth.firebase_auth.verify_id_token")
def test_unrecognised_role_value_defaults_to_clinician(mock_verify, mock_app):
    mock_verify.return_value = {"uid": "u1", "role": "superuser"}
    response = client.get("/protected", headers=_bearer())
    assert response.json()["role"] == "clinician"


@pytest.mark.parametrize(
    "exc",
    [
        firebase_auth.ExpiredIdTokenError("expired", cause=None),
        firebase_auth.RevokedIdTokenError("revoked"),
        firebase_auth.InvalidIdTokenError("wrong audience"),
        firebase_auth.CertificateFetchError("cert fetch failed", cause=None),
    ],
)
@patch("app.auth._firebase_app")
@patch("app.auth.firebase_auth.verify_id_token")
def test_every_verification_failure_is_401_not_a_500(mock_verify, mock_app, exc):
    """I2: absent, expired or wrong-audience -> 401. None of these should ever surface as a 500 —
    a verification-infrastructure outage is still a fail-closed 401, not an internal error."""
    mock_verify.side_effect = exc
    response = client.get("/protected", headers=_bearer())
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


@patch("app.auth._firebase_app")
@patch("app.auth.firebase_auth.verify_id_token")
def test_clinician_calling_an_admin_route_is_403(mock_verify, mock_app):
    """A2's literal acceptance test."""
    mock_verify.return_value = {"uid": "clinician-1", "role": "clinician"}
    response = client.get("/admin-only", headers=_bearer())
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@patch("app.auth._firebase_app")
@patch("app.auth.firebase_auth.verify_id_token")
def test_admin_calling_an_admin_route_is_200(mock_verify, mock_app):
    mock_verify.return_value = {"uid": "admin-1", "role": "admin"}
    response = client.get("/admin-only", headers=_bearer())
    assert response.status_code == 200


@patch("app.auth._firebase_app")
@patch("app.auth.firebase_auth.verify_id_token")
def test_admin_calling_a_plain_clinician_route_is_200(mock_verify, mock_app):
    """Admin is a superset of clinician (see the docstring on require_role)."""
    mock_verify.return_value = {"uid": "admin-1", "role": "admin"}
    response = client.get("/protected", headers=_bearer())
    assert response.status_code == 200


@patch("app.auth._firebase_app")
@patch("app.auth.firebase_auth.verify_id_token")
def test_check_revoked_is_requested(mock_verify, mock_app):
    """A4: a disabled clinician must lose access before their token would otherwise expire."""
    mock_verify.return_value = {"uid": "u1", "role": "clinician"}
    client.get("/protected", headers=_bearer("some-token"))
    assert mock_verify.call_args.kwargs.get("check_revoked") is True
