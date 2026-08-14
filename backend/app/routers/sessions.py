"""Session upload and automatic segmentation (D1-D8, SRS §4.2 D).

``POST /v1/sessions`` registers an uploaded recording (D1-D3): montage validation and the
ten-minute duration cap both happen here, server-side, once the object has actually landed in
the bucket -- never trusted from the client. ``POST /v1/sessions/{sid}/segment`` runs the
pipeline D4-D8 describe: window -> Freq-72 / envelope -> whole-session z-score -> ensemble ->
restrict to the participant's calibrated output space -> smooth -> build bouts -> flag.

No metric is computed here. F1's gate (SegmentationNotApproved) belongs to the review/approval
step, not this one -- segmenting a recording is not the same act as trusting its numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.adapters.firestore_repo import COLLECTIONS, DocumentStore, get_document_store
from app.adapters.storage import ObjectStore, get_object_store
from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.domain import audit
from app.domain.bouts import Bout, build_bouts
from app.domain.calibration import restrict_to_calibrated
from app.domain.calibration_record import load_active
from app.domain.features import extract_freq72
from app.domain.normalisation import zscore_envelopes, zscore_features
from app.domain.ownership import load_owned_participant
from app.domain.session_capture import parse_session_csv
from app.domain.sessions import Session, SessionStatus, mark_segmented, new_session
from app.domain.signal import bandpass_filter, linear_envelope
from app.domain.smoothing import enforce_minimum_dwell, majority_vote_smooth
from app.domain.windowing import SAMPLING_RATE_HZ, sliding_windows
from app.errors import NotCalibrated, NotFound
from app.serving.onnx_predictor import get_ensemble

router = APIRouter(tags=["sessions"])


class SessionCreate(BaseModel):
    participant_id: str
    object_name: str  # returned by POST /v1/uploads/sign, now populated in the bucket


class SessionOut(BaseModel):
    id: str
    participant_id: str
    status: str
    sample_count: int
    duration_seconds: float
    model_version: str | None
    calibration_version: int | None
    window_count: int | None

    @staticmethod
    def from_domain(session: Session) -> SessionOut:
        return SessionOut(
            id=session.id,
            participant_id=session.participant_id,
            status=session.status.value,
            sample_count=session.sample_count,
            duration_seconds=session.duration_seconds,
            model_version=session.model_version,
            calibration_version=session.calibration_version,
            window_count=session.window_count,
        )


class BoutOut(BaseModel):
    id: str
    task: str
    start_ms: float
    end_ms: float
    window_count: int
    mean_confidence: float
    flagged: bool
    flag_reasons: list[str]

    @staticmethod
    def from_domain(bout: Bout) -> BoutOut:
        return BoutOut(
            id=bout.id,
            task=bout.task,
            start_ms=bout.start_ms,
            end_ms=bout.end_ms,
            window_count=bout.window_count,
            mean_confidence=bout.mean_confidence,
            flagged=bout.flagged,
            flag_reasons=list(bout.flag_reasons),
        )


class SegmentationOut(BaseModel):
    session: SessionOut
    bouts: list[BoutOut]
    flagged_count: int


StoreDep = Annotated[DocumentStore, Depends(get_document_store)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]


def _write_audit(store: DocumentStore, entry: audit.AuditEntry) -> None:
    store.set(COLLECTIONS.AUDIT, entry.id, entry.to_document())


def _load_session(store: DocumentStore, user: CurrentUser, session_id: str) -> Session:
    """Fetch a session, enforcing A3 through its owning participant -- the same not-found-vs-
    forbidden judgement call ``load_owned_participant`` makes, extended to a resource that is
    keyed by session id but scoped by participant."""
    doc = store.get(COLLECTIONS.SESSIONS, session_id)
    if doc is None:
        raise NotFound("session", session_id)
    session = Session.from_document(doc)
    load_owned_participant(store, user, session.participant_id)  # raises NotFound if not mine
    return session


@router.post(
    "/v1/sessions",
    response_model=SessionOut,
    status_code=201,
    summary="Register an uploaded session recording",
)
def create_session(
    body: SessionCreate, user: UserDep, store: StoreDep, objects: ObjectStoreDep
) -> SessionOut:
    participant = load_owned_participant(store, user, body.participant_id)

    raw_bytes = objects.read_bytes(body.object_name)
    signal = parse_session_csv(raw_bytes)  # raises MontageRejected / SessionTooLong

    session = new_session(
        participant_id=participant.id,
        created_by=user.uid,
        source_object=body.object_name,
        sample_count=signal.shape[0],
        duration_seconds=signal.shape[0] / SAMPLING_RATE_HZ,
    )
    store.set(COLLECTIONS.SESSIONS, session.id, session.to_document())
    _write_audit(
        store,
        audit.record(
            actor=user.uid,
            action="session.create",
            target_type="session",
            target_id=session.id,
            after=session.to_document(),
        ),
    )
    return SessionOut.from_domain(session)


@router.post(
    "/v1/sessions/{session_id}/segment",
    response_model=SegmentationOut,
    summary="Run automatic segmentation over an uploaded session",
)
def segment_session(
    session_id: str, user: UserDep, store: StoreDep, objects: ObjectStoreDep
) -> SegmentationOut:
    session = _load_session(store, user, session_id)
    settings = get_settings()

    calibration = load_active(store, session.participant_id)
    calibrated = (
        ()
        if calibration is None
        else tuple(
            task for task, summary in calibration.per_task.items() if summary.status == "calibrated"
        )
    )
    if not calibrated:
        raise NotCalibrated(session.participant_id)

    raw_bytes = objects.read_bytes(session.source_object)
    signal = parse_session_csv(raw_bytes)

    # D4: the whole continuous recording is filtered once -- never per-window, never per-block
    # (there are no task blocks in a session upload the way there are in a calibration capture).
    filtered = bandpass_filter(signal)
    envelope = linear_envelope(filtered)

    raw_windows = sliding_windows(filtered)  # (n_windows, 480, 9), time-major
    env_windows = sliding_windows(envelope)  # (n_windows, 480, 9), time-major

    features = extract_freq72(np.ascontiguousarray(raw_windows))
    features_z = zscore_features(features)

    # The ONNX ResNet graph and zscore_envelopes both expect channel-major windows
    # (n_windows, 9, 480); sliding_windows produces time-major ones, matching the shape
    # calibration_capture.py's envelope-peak pooling needs. Transpose here, once, at the seam.
    envelope_channel_major = np.ascontiguousarray(env_windows.transpose(0, 2, 1))
    envelope_z = zscore_envelopes(envelope_channel_major)

    ensemble = get_ensemble(str(Path(settings.artefact_dir).resolve()))
    prediction = ensemble.predict(features_z, envelope_z)

    # D5: the output space is restricted to what this participant is calibrated for, before
    # anything downstream (labels, confidence, smoothing, bouts) ever sees the probabilities.
    restricted = restrict_to_calibrated(prediction.probabilities, calibrated)
    label_indices = restricted.argmax(axis=1)

    # D6: five-window majority vote, then per-class minimum dwell.
    smoothed = majority_vote_smooth(label_indices)
    dwelled = enforce_minimum_dwell(smoothed)

    # D7 + D8: bout construction and review flagging, against the restricted probabilities the
    # final labels came from.
    bouts = build_bouts(
        session.id,
        dwelled,
        restricted,
        dns_wak_margin=settings.dns_wak_margin,
        low_confidence_threshold=settings.low_confidence_threshold,
    )

    for bout in bouts:
        store.set(COLLECTIONS.BOUTS, bout.id, bout.to_document())

    updated = mark_segmented(
        session,
        model_version=prediction.model_version,
        model_hash=prediction.model_hash,
        calibration_version=calibration.version,
        window_count=int(restricted.shape[0]),
    )
    store.update(COLLECTIONS.SESSIONS, session.id, updated.to_document())
    _write_audit(
        store,
        audit.record(
            actor=user.uid,
            action="session.segment",
            target_type="session",
            target_id=session.id,
            before={"status": SessionStatus.UPLOADED.value},
            after=updated.to_document(),
        ),
    )

    return SegmentationOut(
        session=SessionOut.from_domain(updated),
        bouts=[BoutOut.from_domain(b) for b in bouts],
        flagged_count=sum(1 for b in bouts if b.flagged),
    )
