"""``POST /v1/uploads/sign`` — mint a V4 signed URL for a direct-to-bucket upload (ADR-002)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.adapters.storage import (
    SIGNED_URL_TTL_SECONDS,
    ObjectStore,
    get_object_store,
    new_object_name,
)
from app.auth import CurrentUser, get_current_user
from app.errors import RateLimited
from app.middleware.rate_limit import BUCKET_UPLOAD_SIGN, InProcessRateLimiter, get_rate_limiter

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])


class UploadKind(StrEnum):
    CALIBRATION = "calibration"
    SESSION = "session"


#: The content types a browser actually produces for the two accepted file shapes. ``file.type``
#: is empty for a ``.csv.gz`` in some browsers and ``application/octet-stream`` in others, so
#: both are admitted. An allow-list rather than a free string because this value is bound into
#: the signature and therefore into what the bucket will accept on the subsequent PUT.
AllowedContentType = Literal[
    "text/csv",
    "text/plain",
    "application/gzip",
    "application/x-gzip",
    "application/octet-stream",
]


class SignRequest(BaseModel):
    kind: UploadKind
    #: Constrained because it is interpolated into an object name. The charset excludes ``/``
    #: and ``.``, so a caller cannot introduce a path segment or an extension of its own
    #: (I1: validation belongs at every boundary, and this is the one that reaches GCS).
    #: Deliberately broader than the uuid4 that ``new_participant`` actually mints -- the
    #: constraint should be what safety requires, not an incidental tightening.
    participant_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    content_type: AllowedContentType = "text/csv"


class SignResponse(BaseModel):
    object_name: str
    upload_url: str
    method: str = "PUT"
    expires_in_seconds: int = SIGNED_URL_TTL_SECONDS


UserDep = Annotated[CurrentUser, Depends(get_current_user)]
StoreDep = Annotated[ObjectStore, Depends(get_object_store)]
RateLimiterDep = Annotated[InProcessRateLimiter, Depends(get_rate_limiter)]


@router.post("/sign", response_model=SignResponse, summary="Mint a signed upload URL")
def sign_upload(
    body: SignRequest, user: UserDep, store: StoreDep, limiter: RateLimiterDep
) -> SignResponse:
    # Minting is nearly free server-side, but every URL is a licence to write an object into the
    # bucket, and nothing downstream charges for storage. Bounded on its own generous quota
    # rather than sharing segmentation's (see InProcessRateLimiter's docstring).
    allowed, _remaining = limiter.check(user.uid, bucket=BUCKET_UPLOAD_SIGN)
    if not allowed:
        raise RateLimited(limiter.limit_for(BUCKET_UPLOAD_SIGN))

    # Ownership is still not checked here, and still deliberately: minting commits nothing, and
    # the object is inert until POST /v1/calibrations or /v1/sessions names it, at which point
    # load_owned_participant runs. What *has* changed is that the caller's uid is now part of
    # the object name, so the name itself carries who is entitled to register it -- previously
    # any well-formed string was accepted there, and an object name was a bearer token nobody
    # checked.
    object_name = new_object_name(body.kind.value, user.uid, body.participant_id)
    url = store.signed_upload_url(object_name, body.content_type)
    return SignResponse(object_name=object_name, upload_url=url)
