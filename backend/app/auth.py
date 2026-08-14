"""Firebase ID-token verification, applied in the application rather than at the Cloud Run
boundary (ADR-004).

Cloud Run allows unauthenticated invocation; every route other than ``/v1/health`` must instead
verify a Firebase ID token here. This is the *only* module that touches ``firebase_admin.auth``,
so a wrong-audience or expired token has exactly one place it could slip through, and it is this
module's job to fail closed on every path that is not a clean, current, correctly-issued token.

A handler never sees the raw token or the decoded claim dict — it receives a small, typed
:class:`CurrentUser`. That is deliberate: the audit log (E8) and the participant-ownership check
(A3) both need a stable identity, not whatever shape Firebase happens to hand back.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import firebase_admin
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth

from app.errors import Forbidden, Unauthenticated

Role = Literal["clinician", "admin"]

#: auto_error=False so an absent header reaches our own 401 envelope rather than FastAPI's
#: default 403 "Not authenticated" — the error code must be I2's, not the library's.
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    """The identity that reaches the domain layer. Never the raw token or claim dict."""

    uid: str
    email: str | None
    role: Role


@lru_cache(maxsize=1)
def _firebase_app() -> firebase_admin.App:
    """Initialise the Admin SDK exactly once, from ambient Application Default Credentials.

    Cloud Run supplies these automatically via the attached service account. Nothing in this
    module ever holds, reads, or accepts a service-account key file — see HANDOFF_MYOLENS.md §3.
    """
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app()


def _decode(token: str) -> dict:
    """Verify a bearer token and return its claims, or raise :class:`Unauthenticated`.

    ``check_revoked=True`` costs an extra call to the Firebase backend per request, and is worth
    it here: a clinician's access must actually stop the moment an admin disables their account
    (A4), not merely once their existing token happens to expire.
    """
    _firebase_app()
    try:
        return firebase_auth.verify_id_token(token, check_revoked=True)
    except firebase_auth.ExpiredIdTokenError:
        raise Unauthenticated("The session has expired. Sign in again.") from None
    except firebase_auth.RevokedIdTokenError:
        raise Unauthenticated("This session was revoked.") from None
    except firebase_auth.InvalidIdTokenError as exc:
        # Covers a wrong-audience or wrong-issuer token along with every other malformed case —
        # the Admin SDK does not distinguish them further, and neither does this module.
        raise Unauthenticated("The token is invalid or was not issued for this project.") from exc
    except firebase_auth.CertificateFetchError as exc:
        # A verification-infrastructure failure, not a client fault — but the caller still gets
        # no access. Fail closed, not open.
        raise Unauthenticated("Identity could not be verified right now.") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """FastAPI dependency: the identity of the caller, or a 401 (I2, A1)."""
    if credentials is None or not credentials.credentials:
        raise Unauthenticated("No bearer token was supplied.")

    claims = _decode(credentials.credentials)
    role = claims.get("role")
    if role not in ("clinician", "admin"):
        # No custom claim yet, or a value that predates A4's role set. Provisioned accounts are
        # clinicians until an admin says otherwise (A4) — never silently admin.
        role = "clinician"
    return CurrentUser(uid=claims["uid"], email=claims.get("email"), role=role)


def require_role(required_role: Role):
    """Dependency factory: 403s a caller whose role is neither ``required_role`` nor admin (A2).

    Admin is a superset of clinician by design — an admin who cannot also do what a clinician
    does could not administer a clinician's account. The reverse never holds: a clinician
    dependency built from ``require_role("admin")`` still requires the admin claim exactly.
    """

    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role != required_role and user.role != "admin":
            raise Forbidden(required_role)
        return user

    return _check


#: Convenience dependency for the routes A4 reserves to admins.
require_admin = require_role("admin")
