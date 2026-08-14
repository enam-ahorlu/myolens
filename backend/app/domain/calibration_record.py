"""The persisted calibration record (schema ``participants/{pid}/calibrations/{cid}`` in the
plan of record's §9 data model).

Stored as a flat document with a ``participantId`` field rather than a true Firestore
subcollection — the same adaptation ``routers/participants.py`` and ``domain/audit.py`` already
make against ``adapters.firestore_repo.DocumentStore``'s deliberately narrow
collection-plus-doc-id protocol. See that protocol's docstring for why it stays narrow.

**C5 — recalibration supersedes, never overwrites.** A new calibration upload always creates a
new record at ``version = previous_active.version + 1`` and flips the previous active record's
``active`` flag to ``False``; nothing is ever deleted or mutated in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class TaskCalibrationSummary:
    window_count: int
    block_count: int
    status: str  # "calibrated" | "insufficient" | "not_attempted" (see domain.calibration)

    def to_document(self) -> dict[str, Any]:
        return {
            "windowCount": self.window_count,
            "blockCount": self.block_count,
            "status": self.status,
            "sufficient": self.status == "calibrated",
        }

    @staticmethod
    def from_document(doc: dict[str, Any]) -> TaskCalibrationSummary:
        return TaskCalibrationSummary(
            window_count=doc["windowCount"], block_count=doc["blockCount"], status=doc["status"]
        )


@dataclass(frozen=True)
class CalibrationRecord:
    id: str
    participant_id: str
    version: int
    created_at: datetime
    created_by: str
    source_object: str
    per_task: dict[str, TaskCalibrationSummary]
    envelope_peak: tuple[float, ...]  # 9 values, the %CAL reference vector
    mahalanobis: float
    difficulty_band: str
    ood_flag: bool
    active: bool

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "participantId": self.participant_id,
            "version": self.version,
            "createdAt": self.created_at.isoformat(),
            "createdBy": self.created_by,
            "sourceObject": self.source_object,
            "perTask": {task: s.to_document() for task, s in self.per_task.items()},
            "envelopePeak": list(self.envelope_peak),
            "mahalanobis": self.mahalanobis,
            "difficultyBand": self.difficulty_band,
            "oodFlag": self.ood_flag,
            "active": self.active,
        }

    @staticmethod
    def from_document(doc: dict[str, Any]) -> CalibrationRecord:
        return CalibrationRecord(
            id=doc["id"],
            participant_id=doc["participantId"],
            version=doc["version"],
            created_at=datetime.fromisoformat(doc["createdAt"]),
            created_by=doc["createdBy"],
            source_object=doc["sourceObject"],
            per_task={
                task: TaskCalibrationSummary.from_document(s) for task, s in doc["perTask"].items()
            },
            envelope_peak=tuple(doc["envelopePeak"]),
            mahalanobis=doc["mahalanobis"],
            difficulty_band=doc["difficultyBand"],
            ood_flag=doc["oodFlag"],
            active=doc["active"],
        )


def new_calibration_record(
    *,
    participant_id: str,
    version: int,
    created_by: str,
    source_object: str,
    per_task: dict[str, TaskCalibrationSummary],
    envelope_peak: tuple[float, ...],
    mahalanobis: float,
    difficulty_band: str,
    ood_flag: bool,
) -> CalibrationRecord:
    return CalibrationRecord(
        id=str(uuid4()),
        participant_id=participant_id,
        version=version,
        created_at=datetime.now(UTC),
        created_by=created_by,
        source_object=source_object,
        per_task=per_task,
        envelope_peak=envelope_peak,
        mahalanobis=mahalanobis,
        difficulty_band=difficulty_band,
        ood_flag=ood_flag,
        active=True,
    )
