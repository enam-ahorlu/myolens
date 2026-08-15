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

import math
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.adapters.firestore_repo import COLLECTIONS, DocumentStore, get_document_store
from app.adapters.storage import ObjectStore, get_object_store
from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.domain import audit
from app.domain.bouts import (
    Bout,
    ExclusionReason,
    build_bouts,
    exclude_bout,
    merge_bouts,
    relabel_bout,
    split_bout,
)
from app.domain.calibration import restrict_to_calibrated
from app.domain.calibration_record import CalibrationRecord, load_active
from app.domain.features import extract_freq72
from app.domain.metrics import CoContractionResult, TaskMetrics, compute_task_metrics, percent_cal
from app.domain.montage import MONTAGE
from app.domain.normalisation import zscore_envelopes, zscore_features
from app.domain.ownership import load_owned_participant
from app.domain.session_capture import parse_session_csv
from app.domain.sessions import Session, SessionStatus, mark_approved, mark_segmented, new_session
from app.domain.signal import bandpass_filter, linear_envelope
from app.domain.smoothing import enforce_minimum_dwell, majority_vote_smooth
from app.domain.windowing import SAMPLING_RATE_HZ, sliding_windows
from app.errors import (
    ErrorCode,
    MyoLensError,
    NotCalibrated,
    NotFound,
    SegmentationLocked,
    SegmentationNotApproved,
    SegmentationNotReady,
)
from app.routers.session_report import render_session_report_pdf
from app.serving.onnx_predictor import get_ensemble

router = APIRouter(tags=["sessions"])


class InvalidCorrection(MyoLensError):
    """A bout correction request that is malformed, targets an uncalibrated task, or specifies
    an invalid split/merge -- an operator-fixable input error, not a programming error."""

    def __init__(self, message: str, details: list[dict] | None = None) -> None:
        super().__init__(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message=message,
            details=details or [],
        )


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
    excluded: bool
    exclusion_reason: str | None
    corrected: bool
    original_task: str | None

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
            excluded=bout.excluded,
            exclusion_reason=bout.exclusion_reason,
            corrected=bout.corrected,
            original_task=bout.original_task,
        )


class SegmentationOut(BaseModel):
    session: SessionOut
    bouts: list[BoutOut]
    flagged_count: int


class BoutCorrection(BaseModel):
    """A single review operation (E3-E6). Exactly one operation per request -- fields not used
    by ``op`` are ignored rather than validated, keeping the four operations' payloads simple
    instead of forcing a discriminated-union schema onto callers for what is, in practice, four
    small and unrelated shapes."""

    op: Literal["relabel", "split", "merge", "exclude"]
    task: str | None = None  # relabel: the new task
    at_window: int | None = None  # split: absolute window index the second half starts at
    neighbor_bout_id: str | None = None  # merge: the adjacent same-label bout to merge with
    reason: Literal["artefact", "transition", "unobserved"] | None = None  # exclude


class BoutCorrectionOut(BaseModel):
    bouts: list[BoutOut]
    removed_bout_ids: list[str]


class CoContractionOut(BaseModel):
    value: float | None
    windows_used: int
    windows_total: int

    @staticmethod
    def from_domain(result: CoContractionResult) -> CoContractionOut:
        return CoContractionOut(
            value=result.value,
            windows_used=result.windows_used,
            windows_total=result.windows_total,
        )


class TaskMetricsOut(BaseModel):
    task: str
    bout_count: int
    bout_duration_total_s: float
    #: 9 values, %CAL, in montage channel order -- ``None`` where the calibration channel it
    #: would be divided by produced no usable signal (§3.3's amp_mean/amp_peak).
    amp_mean: list[float | None]
    amp_peak: list[float | None]
    duty_cycle: list[float]
    cci_knee: CoContractionOut
    cci_ankle: CoContractionOut
    model_confidence_mean: float
    correction_rate_pct: float

    @staticmethod
    def from_domain(metrics: TaskMetrics) -> TaskMetricsOut:
        return TaskMetricsOut(
            task=metrics.task,
            bout_count=metrics.bout_count,
            bout_duration_total_s=metrics.bout_duration_total_s,
            amp_mean=[_none_if_nan(v) for v in metrics.amp_mean],
            amp_peak=[_none_if_nan(v) for v in metrics.amp_peak],
            duty_cycle=list(metrics.duty_cycle),
            cci_knee=CoContractionOut.from_domain(metrics.cci_knee),
            cci_ankle=CoContractionOut.from_domain(metrics.cci_ankle),
            model_confidence_mean=metrics.model_confidence_mean,
            correction_rate_pct=metrics.correction_rate_pct,
        )


class SessionMetricsOut(BaseModel):
    """F1's §3.3 metric set, one entry per task with at least one approved (non-excluded) bout.

    A task the operator excluded every bout of, or that never appeared in this session at all,
    is simply absent from ``tasks`` -- there is nothing in §3.3 to compute for zero windows, and
    a zero-filled card would misread as a measured absence of activity rather than an absence of
    data.
    """

    session_id: str
    channels: list[str]  # the 9-channel montage, in order -- labels the amp_mean/amp_peak arrays
    flagged_count: int
    tasks: list[TaskMetricsOut]


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


def _load_bout(store: DocumentStore, session_id: str, bout_id: str) -> Bout:
    doc = store.get(COLLECTIONS.BOUTS, bout_id)
    if doc is None or doc["sessionId"] != session_id:
        raise NotFound("bout", bout_id)
    return Bout.from_document(doc)


def _calibrated_tasks(calibration: CalibrationRecord | None) -> tuple[str, ...]:
    if calibration is None:
        return ()
    return tuple(
        task for task, summary in calibration.per_task.items() if summary.status == "calibrated"
    )


def _load_calibration_version(
    store: DocumentStore, participant_id: str, version: int | None
) -> CalibrationRecord:
    """The *exact* calibration a session was segmented against (recorded on the session at
    segmentation time), not necessarily the participant's current active one -- a recalibration
    between segmentation and metrics computation must not silently change a locked session's
    %CAL reference out from under it.
    """
    docs = store.query(COLLECTIONS.CALIBRATIONS, participantId=participant_id, version=version)
    if not docs:
        raise NotFound("calibration", f"{participant_id}@v{version}")
    return CalibrationRecord.from_document(docs[0])


def _none_if_nan(value: float) -> float | None:
    return None if math.isnan(value) else value


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
    calibrated = _calibrated_tasks(calibration)
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


@router.patch(
    "/v1/sessions/{session_id}/bouts/{bout_id}",
    response_model=BoutCorrectionOut,
    summary="Correct one bout: relabel, split, merge, or exclude (E3-E6)",
)
def correct_bout(
    session_id: str, bout_id: str, body: BoutCorrection, user: UserDep, store: StoreDep
) -> BoutCorrectionOut:
    session = _load_session(store, user, session_id)
    if session.status == SessionStatus.UPLOADED:
        raise SegmentationNotReady(session.id)
    if session.status == SessionStatus.APPROVED:
        raise SegmentationLocked(session.id)

    bout = _load_bout(store, session.id, bout_id)

    if body.op == "relabel":
        if body.task is None:
            raise InvalidCorrection("relabel requires 'task'")
        calibrated = _calibrated_tasks(load_active(store, session.participant_id))
        if body.task not in calibrated:
            raise InvalidCorrection(
                f"'{body.task}' is not a task this participant is calibrated for",
                details=[{"task": body.task, "calibrated_tasks": list(calibrated)}],
            )
        updated = relabel_bout(bout, body.task)
        store.update(COLLECTIONS.BOUTS, updated.id, updated.to_document())
        _write_audit(
            store,
            audit.record(
                actor=user.uid,
                action="bout.relabel",
                target_type="bout",
                target_id=bout.id,
                before=bout.to_document(),
                after=updated.to_document(),
            ),
        )
        return BoutCorrectionOut(bouts=[BoutOut.from_domain(updated)], removed_bout_ids=[])

    if body.op == "exclude":
        if body.reason is None:
            raise InvalidCorrection("exclude requires 'reason'")
        updated = exclude_bout(bout, ExclusionReason(body.reason))
        store.update(COLLECTIONS.BOUTS, updated.id, updated.to_document())
        _write_audit(
            store,
            audit.record(
                actor=user.uid,
                action="bout.exclude",
                target_type="bout",
                target_id=bout.id,
                before=bout.to_document(),
                after=updated.to_document(),
            ),
        )
        return BoutCorrectionOut(bouts=[BoutOut.from_domain(updated)], removed_bout_ids=[])

    if body.op == "split":
        if body.at_window is None:
            raise InvalidCorrection("split requires 'at_window'")
        try:
            first, second = split_bout(bout, body.at_window)
        except ValueError as exc:
            raise InvalidCorrection(str(exc)) from exc
        store.update(COLLECTIONS.BOUTS, first.id, first.to_document())
        store.set(COLLECTIONS.BOUTS, second.id, second.to_document())
        _write_audit(
            store,
            audit.record(
                actor=user.uid,
                action="bout.split",
                target_type="bout",
                target_id=bout.id,
                before=bout.to_document(),
                after={"first": first.to_document(), "second": second.to_document()},
            ),
        )
        return BoutCorrectionOut(
            bouts=[BoutOut.from_domain(first), BoutOut.from_domain(second)], removed_bout_ids=[]
        )

    # op == "merge"
    if body.neighbor_bout_id is None:
        raise InvalidCorrection("merge requires 'neighbor_bout_id'")
    neighbor = _load_bout(store, session.id, body.neighbor_bout_id)
    earlier, later = (
        (bout, neighbor) if bout.start_window < neighbor.start_window else (neighbor, bout)
    )
    try:
        merged = merge_bouts(earlier, later)
    except ValueError as exc:
        raise InvalidCorrection(str(exc)) from exc

    store.update(COLLECTIONS.BOUTS, merged.id, merged.to_document())
    removed_id = later.id if merged.id == earlier.id else earlier.id
    store.delete(COLLECTIONS.BOUTS, removed_id)
    _write_audit(
        store,
        audit.record(
            actor=user.uid,
            action="bout.merge",
            target_type="bout",
            target_id=merged.id,
            before={"earlier": earlier.to_document(), "later": later.to_document()},
            after=merged.to_document(),
        ),
    )
    return BoutCorrectionOut(bouts=[BoutOut.from_domain(merged)], removed_bout_ids=[removed_id])


@router.post(
    "/v1/sessions/{session_id}/approve",
    response_model=SessionOut,
    summary="Approve the segmentation -- the explicit gate before any metric exists (E7)",
)
def approve_session(session_id: str, user: UserDep, store: StoreDep) -> SessionOut:
    session = _load_session(store, user, session_id)
    if session.status == SessionStatus.UPLOADED:
        raise SegmentationNotReady(session.id)
    if session.status == SessionStatus.APPROVED:
        raise SegmentationLocked(session.id)

    updated = mark_approved(session)
    store.update(COLLECTIONS.SESSIONS, session.id, updated.to_document())
    _write_audit(
        store,
        audit.record(
            actor=user.uid,
            action="session.approve",
            target_type="session",
            target_id=session.id,
            before={"status": SessionStatus.SEGMENTED.value},
            after=updated.to_document(),
        ),
    )
    return SessionOut.from_domain(updated)


def _load_or_compute_metrics(
    session: Session, store: DocumentStore, objects: ObjectStore
) -> SessionMetricsOut:
    """F1's §3.3 metric set for an approved session -- shared by the metrics endpoint and the
    PDF export endpoint (G1) so both read exactly the same numbers, computed exactly once.

    Raises :class:`SegmentationNotApproved` (412) itself rather than leaving the gate to each
    caller -- FR-08/E7/F1 say no metric before approval, and a route that forgot to check first
    would otherwise read a stale or nonexistent cache entry as "nothing to report" instead of
    "not allowed yet".
    """
    bout_docs = store.query(COLLECTIONS.BOUTS, sessionId=session.id)
    bouts = sorted((Bout.from_document(d) for d in bout_docs), key=lambda b: b.start_window)
    flagged_count = sum(1 for b in bouts if b.flagged)

    if session.status != SessionStatus.APPROVED:
        raise SegmentationNotApproved(session.id, flagged_count)

    # Once approved, corrections are refused (SegmentationLocked) and the bouts underlying this
    # computation can never change again -- so the result is cached at COLLECTIONS.METRICS,
    # keyed by session id, and computed at most once per session.
    cached = store.get(COLLECTIONS.METRICS, session.id)
    if cached is not None:
        return SessionMetricsOut.model_validate(cached)

    calibration = _load_calibration_version(
        store, session.participant_id, session.calibration_version
    )
    calibration_peak = np.array(calibration.envelope_peak, dtype=np.float64)

    # Recomputed from the source recording rather than persisted at segmentation time: D4
    # guarantees the pipeline is byte-identical for identical input, so the per-window envelope
    # this reproduces is exactly the one segmentation used, without a second array to keep in
    # sync with the bouts derived from it.
    raw_bytes = objects.read_bytes(session.source_object)
    signal = parse_session_csv(raw_bytes)
    filtered = bandpass_filter(signal)
    envelope = linear_envelope(filtered)
    env_windows = sliding_windows(envelope)  # (n_windows, 480, 9)
    # Per-window amplitude is the window's peak envelope, matching how the calibration capture's
    # own %CAL reference was pooled (app.domain.calibration_capture.analyse_capture).
    amplitude = np.ascontiguousarray(env_windows).max(axis=1)  # (n_windows, 9)
    amplitude_pct_cal = percent_cal(amplitude, calibration_peak)

    if amplitude_pct_cal.shape[0] != session.window_count:
        # Should be unreachable under D4's determinism guarantee -- the source object and the
        # pipeline are both fixed once a session is segmented. Surfacing this as an internal
        # error rather than silently truncating/padding is deliberate: a mismatch here means the
        # recording behind ``source_object`` changed after segmentation, and every metric below
        # would be reading windows against the wrong bout boundaries.
        raise MyoLensError(
            status_code=500,
            code=ErrorCode.INTERNAL,
            message="Recomputed window count does not match the segmented session.",
            details=[
                {
                    "expected": session.window_count,
                    "recomputed": int(amplitude_pct_cal.shape[0]),
                }
            ],
        )

    by_task: dict[str, list[Bout]] = {}
    for bout in bouts:
        if bout.excluded:
            continue
        by_task.setdefault(bout.task, []).append(bout)

    tasks = [
        TaskMetricsOut.from_domain(compute_task_metrics(task, task_bouts, amplitude_pct_cal))
        for task, task_bouts in sorted(by_task.items())
    ]

    result = SessionMetricsOut(
        session_id=session.id,
        channels=list(MONTAGE),
        flagged_count=flagged_count,
        tasks=tasks,
    )
    store.set(COLLECTIONS.METRICS, session.id, result.model_dump())
    return result


@router.get(
    "/v1/sessions/{session_id}/metrics",
    response_model=SessionMetricsOut,
    summary="Compute the §3.3 metric set on an approved segmentation (F1)",
)
def get_session_metrics(
    session_id: str, user: UserDep, store: StoreDep, objects: ObjectStoreDep
) -> SessionMetricsOut:
    session = _load_session(store, user, session_id)
    return _load_or_compute_metrics(session, store, objects)


@router.get(
    "/v1/sessions/{session_id}/export",
    summary="Export a PDF report of the approved segmentation and its metrics (G1)",
)
def export_session(
    session_id: str, user: UserDep, store: StoreDep, objects: ObjectStoreDep
) -> Response:
    session = _load_session(store, user, session_id)
    participant = load_owned_participant(store, user, session.participant_id)
    # Same gate, same numbers as GET .../metrics -- this raises SegmentationNotApproved itself
    # if the session isn't approved yet, so the export can never show metrics the clinician
    # hasn't signed off on either.
    metrics = _load_or_compute_metrics(session, store, objects)

    bout_docs = store.query(COLLECTIONS.BOUTS, sessionId=session.id)
    bouts = sorted((Bout.from_document(d) for d in bout_docs), key=lambda b: b.start_window)
    calibration = _load_calibration_version(
        store, session.participant_id, session.calibration_version
    )

    pdf_bytes = render_session_report_pdf(
        participant_code=participant.code,
        session=session,
        calibration=calibration,
        bouts=bouts,
        metrics=metrics,
    )
    filename = f"myolens-session-{session.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
