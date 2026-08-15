"""The typed error envelope.

Every failure leaves this service in the same shape. A stack trace never reaches a client, and
a refusal is never an unlabelled 500.

MyoLens refuses to proceed more often than most applications, and those refusals are *designed
states* rather than error paths — the out-of-distribution guard and montage rejection are direct
products of measured model limitations. Giving them a stable, machine-readable code makes them
testable and lets the front end render each one as a specific explanation instead of a generic
apology.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    """Stable codes. The front end switches on these; never renumber one."""

    UNAUTHENTICATED = "unauthenticated"  # 401
    FORBIDDEN = "forbidden"  # 403
    NOT_FOUND = "not_found"  # 404
    CONFLICT = "conflict"  # 409
    MONTAGE_REJECTED = "montage_rejected"  # 409
    PRECONDITION_FAILED = "precondition_failed"  # 412
    NOT_CALIBRATED = "not_calibrated"  # 412
    SEGMENTATION_NOT_APPROVED = "segmentation_not_approved"  # 412
    PAYLOAD_TOO_LARGE = "payload_too_large"  # 413
    VALIDATION_FAILED = "validation_failed"  # 422
    OUT_OF_DISTRIBUTION = "out_of_distribution"  # 422
    LOCKED = "locked"  # 423
    RATE_LIMITED = "rate_limited"  # 429
    INTERNAL = "internal"  # 500
    MODEL_UNAVAILABLE = "model_unavailable"  # 503


class ErrorEnvelope(BaseModel):
    """The only error body this service emits."""

    code: ErrorCode
    message: str = Field(description="Plain language, addressed to the operator, never a trace")
    details: list[dict[str, Any]] = Field(default_factory=list)
    request_id: str | None = None


class MyoLensError(HTTPException):
    """Base for every deliberate refusal."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.details = details or []

    def envelope(self, request_id: str | None = None) -> ErrorEnvelope:
        return ErrorEnvelope(
            code=self.code, message=self.message, details=self.details, request_id=request_id
        )


class MontageRejected(MyoLensError):
    """The upload does not satisfy the nine-channel contract."""

    def __init__(self, violations: list[dict[str, Any]]) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.MONTAGE_REJECTED,
            message=(
                "This recording does not match the required nine-channel montage. "
                "Channel names must match exactly and appear in the specified order; "
                "MyoLens will not guess a mapping."
            ),
            details=violations,
        )


class OutOfDistribution(MyoLensError):
    """The calibration capture lies outside the training distribution."""

    def __init__(self, distance: float, threshold: float) -> None:
        super().__init__(
            status_code=422,
            code=ErrorCode.OUT_OF_DISTRIBUTION,
            message=(
                "This participant's calibration lies outside the distribution the model was "
                "trained on, so its predictions cannot be relied upon. MyoLens will not "
                "segment this recording. The calibration is retained."
            ),
            details=[{"mahalanobis": round(distance, 4), "threshold": round(threshold, 4)}],
        )


class NotCalibrated(MyoLensError):
    """Inference attempted for a participant with no usable calibration."""

    def __init__(self, participant_id: str) -> None:
        super().__init__(
            status_code=412,
            code=ErrorCode.NOT_CALIBRATED,
            message=(
                "This participant has no completed calibration. Calibration supplies both the "
                "%CAL amplitude reference and the out-of-distribution check, so segmentation "
                "cannot proceed without it."
            ),
            details=[{"participant_id": participant_id}],
        )


class SegmentationNotApproved(MyoLensError):
    """Metrics requested before a human approved the segmentation."""

    def __init__(self, session_id: str, flagged_bouts: int) -> None:
        super().__init__(
            status_code=412,
            code=ErrorCode.SEGMENTATION_NOT_APPROVED,
            message=(
                "Metrics are locked until the segmentation is approved. No activation or "
                "co-activation metric is computed from an unreviewed segmentation."
            ),
            details=[{"session_id": session_id, "flagged_bouts": flagged_bouts}],
        )


class SegmentationNotReady(MyoLensError):
    """A bout correction or approval was attempted before ``POST /v1/sessions/{id}/segment``
    ever ran, so there are no bouts yet to correct or approve."""

    def __init__(self, session_id: str) -> None:
        super().__init__(
            status_code=412,
            code=ErrorCode.PRECONDITION_FAILED,
            message=(
                "This session has not been segmented yet. Run automatic segmentation before "
                "reviewing or approving it."
            ),
            details=[{"session_id": session_id}],
        )


class SegmentationLocked(MyoLensError):
    """A bout correction, or a second approval, was attempted after E7's gate already closed.

    E7 is described as an *explicit* gate specifically so a clinician's review is a bounded,
    reviewable act — reopening bouts after approval (silently or otherwise) would let the
    segmentation a metric was computed from drift out from under that metric without anyone
    approving the drift.
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(
            status_code=423,
            code=ErrorCode.LOCKED,
            message=(
                "This session's segmentation has already been approved. Corrections and "
                "re-approval are no longer permitted."
            ),
            details=[{"session_id": session_id}],
        )


class NotFound(MyoLensError):
    """No resource of this type and id exists for this caller.

    Deliberately also the response for a resource that exists but belongs to a different
    clinician (A3) — the alternative, a 403, would confirm to an unauthorised caller that a
    given id is real. ADR-004 makes the same call for unauthenticated callers; this extends it
    to authenticated callers requesting someone else's record.
    """

    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message=f"No {resource} with id '{resource_id}' was found.",
            details=[{"resource": resource, "id": resource_id}],
        )


class Unauthenticated(MyoLensError):
    """Absent, malformed, expired or wrong-audience Firebase ID token (I2, A1)."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            status_code=401,
            code=ErrorCode.UNAUTHENTICATED,
            message=f"Sign in required. {reason}",
        )


class Forbidden(MyoLensError):
    """Authenticated, but the caller's role does not permit this route (A2)."""

    def __init__(self, required_role: str) -> None:
        super().__init__(
            status_code=403,
            code=ErrorCode.FORBIDDEN,
            message=f"This action requires the '{required_role}' role.",
        )


class SessionTooLong(MyoLensError):
    """The recording exceeds the accepted duration."""

    def __init__(self, seconds: float, cap_seconds: int) -> None:
        super().__init__(
            status_code=413,
            code=ErrorCode.PAYLOAD_TOO_LARGE,
            message=(
                f"This recording is {seconds:.0f} seconds long. MyoLens accepts sessions of up "
                f"to {cap_seconds} seconds. Split the recording and upload the parts separately."
            ),
            details=[{"seconds": round(seconds, 1), "cap_seconds": cap_seconds}],
        )
