"""The uploaded session recording (schema ``sessions/{sid}``, SRS §4.2 D).

A session is created in two stages, mirroring the calibration upload path (ADR-002): the
browser puts the raw recording directly in the bucket, then ``POST /v1/sessions`` registers the
object against a participant and validates it (D1-D3). ``POST /v1/sessions/{sid}/segment``
(``routers.sessions``) runs the actual pipeline and moves status from ``uploaded`` to
``segmented``. ``POST /v1/sessions/{sid}/approve`` (E7's explicit gate) moves it to ``approved``,
after which bout corrections are refused (``errors.SegmentationLocked``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class SessionStatus(StrEnum):
    UPLOADED = "uploaded"
    SEGMENTED = "segmented"
    APPROVED = "approved"


@dataclass(frozen=True)
class Session:
    id: str
    participant_id: str
    created_by: str
    created_at: datetime
    source_object: str
    sample_count: int
    duration_seconds: float
    status: SessionStatus
    #: Recorded once segmentation runs (D4's provenance requirement, and G1's export field).
    model_version: str | None = None
    model_hash: str | None = None
    calibration_version: int | None = None
    window_count: int | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "participantId": self.participant_id,
            "createdBy": self.created_by,
            "createdAt": self.created_at.isoformat(),
            "sourceObject": self.source_object,
            "sampleCount": self.sample_count,
            "durationSeconds": self.duration_seconds,
            "status": self.status.value,
            "modelVersion": self.model_version,
            "modelHash": self.model_hash,
            "calibrationVersion": self.calibration_version,
            "windowCount": self.window_count,
        }

    @staticmethod
    def from_document(doc: dict[str, Any]) -> Session:
        return Session(
            id=doc["id"],
            participant_id=doc["participantId"],
            created_by=doc["createdBy"],
            created_at=datetime.fromisoformat(doc["createdAt"]),
            source_object=doc["sourceObject"],
            sample_count=doc["sampleCount"],
            duration_seconds=doc["durationSeconds"],
            status=SessionStatus(doc["status"]),
            model_version=doc.get("modelVersion"),
            model_hash=doc.get("modelHash"),
            calibration_version=doc.get("calibrationVersion"),
            window_count=doc.get("windowCount"),
        )


def new_session(
    *,
    participant_id: str,
    created_by: str,
    source_object: str,
    sample_count: int,
    duration_seconds: float,
) -> Session:
    return Session(
        id=str(uuid4()),
        participant_id=participant_id,
        created_by=created_by,
        created_at=datetime.now(UTC),
        source_object=source_object,
        sample_count=sample_count,
        duration_seconds=duration_seconds,
        status=SessionStatus.UPLOADED,
    )


def mark_segmented(
    session: Session,
    *,
    model_version: str,
    model_hash: str,
    calibration_version: int,
    window_count: int,
) -> Session:
    return replace(
        session,
        status=SessionStatus.SEGMENTED,
        model_version=model_version,
        model_hash=model_hash,
        calibration_version=calibration_version,
        window_count=window_count,
    )


def mark_approved(session: Session) -> Session:
    """E7's explicit gate. No field beyond status changes -- who approved it and when is on the
    audit entry ``routers/sessions.py`` writes alongside this, not duplicated onto the session
    document itself."""
    return replace(session, status=SessionStatus.APPROVED)
