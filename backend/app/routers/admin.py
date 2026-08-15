"""Administration: list clinicians and set roles (A4, SRS §4.2 A, "Should").

Reserved to admins via ``require_admin``. There is no Firestore mirror of who exists and what
role they hold -- the Admin SDK's own user directory and its custom claim *are* the source of
truth, so this router reads and writes through ``firebase_auth`` directly rather than maintaining
a second copy that could drift from it.

A role change takes effect "on next token refresh" (A4's acceptance criterion), not
retroactively: an already-issued ID token keeps its old ``role`` claim until the client refreshes
it, exactly the same latency ``get_current_user``'s revocation check already accepts elsewhere.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from firebase_admin import auth as firebase_auth
from pydantic import BaseModel

from app.auth import CurrentUser, require_admin
from app.errors import NotFound

router = APIRouter(tags=["admin"])

Role = Literal["clinician", "admin"]


class ClinicianOut(BaseModel):
    uid: str
    email: str | None
    role: Role
    disabled: bool

    @staticmethod
    def from_record(user_record) -> ClinicianOut:
        claims = user_record.custom_claims or {}
        role = claims.get("role")
        if role not in ("clinician", "admin"):
            # No custom claim yet: provisioned accounts are clinicians until an admin says
            # otherwise -- the same default get_current_user applies to an unclaimed token.
            role = "clinician"
        return ClinicianOut(
            uid=user_record.uid,
            email=user_record.email,
            role=role,
            disabled=user_record.disabled,
        )


class RoleUpdate(BaseModel):
    role: Role


@router.get(
    "/v1/admin/clinicians",
    response_model=list[ClinicianOut],
    summary="List every account and its role",
)
def list_clinicians(_admin: CurrentUser = Depends(require_admin)) -> list[ClinicianOut]:
    return [ClinicianOut.from_record(record) for record in firebase_auth.list_users().iterate_all()]


@router.patch(
    "/v1/admin/clinicians/{uid}/role",
    response_model=ClinicianOut,
    summary="Set a clinician's role",
)
def set_role(
    uid: str, body: RoleUpdate, _admin: CurrentUser = Depends(require_admin)
) -> ClinicianOut:
    try:
        firebase_auth.get_user(uid)
    except firebase_auth.UserNotFoundError:
        raise NotFound("clinician", uid) from None

    firebase_auth.set_custom_user_claims(uid, {"role": body.role})
    updated = firebase_auth.get_user(uid)
    return ClinicianOut.from_record(updated)
