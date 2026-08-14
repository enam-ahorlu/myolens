"""``POST /v1/uploads/sign`` — mint a V4 signed URL for a direct-to-bucket upload (ADR-002)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.adapters.storage import (
    SIGNED_URL_TTL_SECONDS,
    ObjectStore,
    get_object_store,
    new_object_name,
)
from app.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])


class UploadKind(StrEnum):
    CALIBRATION = "calibration"
    SESSION = "session"


class SignRequest(BaseModel):
    kind: UploadKind
    participant_id: str
    content_type: str = "text/csv"


class SignResponse(BaseModel):
    object_name: str
    upload_url: str
    method: str = "PUT"
    expires_in_seconds: int = SIGNED_URL_TTL_SECONDS


UserDep = Annotated[CurrentUser, Depends(get_current_user)]
StoreDep = Annotated[ObjectStore, Depends(get_object_store)]


@router.post("/sign", response_model=SignResponse, summary="Mint a signed upload URL")
def sign_upload(body: SignRequest, user: UserDep, store: StoreDep) -> SignResponse:
    # Deliberately does not check participant ownership here: minting a URL commits nothing,
    # and the object is validated (montage, and — via load_owned_participant — ownership)
    # server-side once it lands and is registered against a participant. Rejecting an
    # unrelated participant id at signing time would gain nothing but complexity, since the
    # object is inert until POST /v1/calibrations or /v1/sessions names it.
    object_name = new_object_name(body.kind.value, body.participant_id)
    url = store.signed_upload_url(object_name, body.content_type)
    return SignResponse(object_name=object_name, upload_url=url)
