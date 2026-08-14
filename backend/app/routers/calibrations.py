"""Calibration upload and retrieval (SRS §4.2 C, plan of record §10).

``POST /v1/calibrations`` is where C1-C4 all meet: it parses the uploaded CSV, assesses
per-task sufficiency (C1/C2), derives the %CAL reference (C3), and runs the out-of-distribution
guard (C4) -- then persists exactly one new, versioned, active record (C5) regardless of whether
the OOD guard passes, because a refused calibration is still evidence a clinician may need to
review, not something to discard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.adapters.firestore_repo import COLLECTIONS, DocumentStore, get_document_store
from app.adapters.storage import ObjectStore, get_object_store
from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.domain import audit
from app.domain.calibration import (
    assess,
    difficulty_band,
    envelope_peak,
    mahalanobis_distance,
)
from app.domain.calibration_capture import (
    analyse_capture,
    parse_calibration_csv,
    session_zscored_features,
)
from app.domain.calibration_record import (
    CalibrationRecord,
    TaskCalibrationSummary,
    load_active,
    new_calibration_record,
)
from app.domain.ood_guard import get_ood_stats
from app.domain.ownership import load_owned_participant
from app.errors import NotCalibrated, OutOfDistribution

router = APIRouter(tags=["calibrations"])


class CalibrationCreate(BaseModel):
    participant_id: str
    object_name: str  # returned by POST /v1/uploads/sign, now populated in the bucket


class TaskCalibrationOut(BaseModel):
    window_count: int
    block_count: int
    status: str
    sufficient: bool

    @staticmethod
    def from_domain(summary: TaskCalibrationSummary) -> TaskCalibrationOut:
        return TaskCalibrationOut(
            window_count=summary.window_count,
            block_count=summary.block_count,
            status=summary.status,
            sufficient=summary.status == "calibrated",
        )


class CalibrationOut(BaseModel):
    id: str
    participant_id: str
    version: int
    created_at: str
    per_task: dict[str, TaskCalibrationOut]
    envelope_peak: list[float]
    mahalanobis: float
    difficulty_band: str
    ood_flag: bool
    active: bool

    @staticmethod
    def from_domain(record: CalibrationRecord) -> CalibrationOut:
        return CalibrationOut(
            id=record.id,
            participant_id=record.participant_id,
            version=record.version,
            created_at=record.created_at.isoformat(),
            per_task={
                task: TaskCalibrationOut.from_domain(summary)
                for task, summary in record.per_task.items()
            },
            envelope_peak=list(record.envelope_peak),
            mahalanobis=record.mahalanobis,
            difficulty_band=record.difficulty_band,
            ood_flag=record.ood_flag,
            active=record.active,
        )


StoreDep = Annotated[DocumentStore, Depends(get_document_store)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]


def _write_audit(store: DocumentStore, entry: audit.AuditEntry) -> None:
    store.set(COLLECTIONS.AUDIT, entry.id, entry.to_document())


@router.post(
    "/v1/calibrations",
    response_model=CalibrationOut,
    status_code=201,
    summary="Register an uploaded calibration capture",
)
def create_calibration(
    body: CalibrationCreate,
    user: UserDep,
    store: StoreDep,
    objects: ObjectStoreDep,
) -> CalibrationOut:
    participant = load_owned_participant(store, user, body.participant_id)
    settings = get_settings()

    csv_bytes = objects.read_bytes(body.object_name)
    blocks = parse_calibration_csv(csv_bytes)
    capture = analyse_capture(blocks)

    assessment = assess(
        capture.counts,
        min_windows=settings.min_calibration_windows,
        min_blocks=settings.min_calibration_blocks,
    )
    per_task = {
        task: TaskCalibrationSummary(
            window_count=cal.window_count, block_count=cal.block_count, status=cal.status
        )
        for task, cal in assessment.items()
    }

    if capture.envelope_peaks.shape[0] > 0:
        peak = envelope_peak(capture.envelope_peaks)
    else:
        peak = [0.0] * 9

    zscored = session_zscored_features(capture)
    if zscored.shape[0] > 0:
        mean, inverse_covariance = get_ood_stats(str(Path(settings.artefact_dir).resolve()))
        distance = mahalanobis_distance(zscored, mean, inverse_covariance)
    else:
        # No usable windows at all -- there is nothing to measure a distance against. Treat as
        # maximally out-of-distribution rather than silently reporting zero, which would read
        # as "matches the training population perfectly."
        distance = float("inf")

    band = difficulty_band(distance, settings.ood_threshold)
    ood_flag = distance >= settings.ood_threshold

    previous = load_active(store, participant.id)
    next_version = 1 if previous is None else previous.version + 1

    record = new_calibration_record(
        participant_id=participant.id,
        version=next_version,
        created_by=user.uid,
        source_object=body.object_name,
        per_task=per_task,
        envelope_peak=tuple(float(v) for v in peak),
        mahalanobis=distance,
        difficulty_band=band,
        ood_flag=ood_flag,
    )

    # C5: supersede, never overwrite. The previous active record is flipped, not deleted.
    if previous is not None:
        superseded = CalibrationRecord(
            id=previous.id,
            participant_id=previous.participant_id,
            version=previous.version,
            created_at=previous.created_at,
            created_by=previous.created_by,
            source_object=previous.source_object,
            per_task=previous.per_task,
            envelope_peak=previous.envelope_peak,
            mahalanobis=previous.mahalanobis,
            difficulty_band=previous.difficulty_band,
            ood_flag=previous.ood_flag,
            active=False,
        )
        store.update(COLLECTIONS.CALIBRATIONS, superseded.id, superseded.to_document())

    # The record is persisted before the OOD refusal is (possibly) raised: per
    # errors.OutOfDistribution's own docstring, "the calibration is retained." A refused
    # calibration is still evidence a clinician needs to see, not something to discard.
    store.set(COLLECTIONS.CALIBRATIONS, record.id, record.to_document())
    _write_audit(
        store,
        audit.record(
            actor=user.uid,
            action="calibration.create",
            target_type="calibration",
            target_id=record.id,
            after=record.to_document(),
        ),
    )

    if ood_flag:
        raise OutOfDistribution(distance, settings.ood_threshold)

    return CalibrationOut.from_domain(record)


@router.get(
    "/v1/participants/{participant_id}/calibration/active",
    response_model=CalibrationOut,
    summary="The participant's current calibration",
)
def get_active_calibration(participant_id: str, user: UserDep, store: StoreDep) -> CalibrationOut:
    participant = load_owned_participant(store, user, participant_id)
    record = load_active(store, participant.id)
    if record is None:
        raise NotCalibrated(participant.id)
    return CalibrationOut.from_domain(record)
