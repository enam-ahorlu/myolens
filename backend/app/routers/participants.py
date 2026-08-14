"""Participant records (SRS §4.2 B).

Every route here requires authentication (I2). Every route scopes reads and writes to the
calling clinician's own participants (A3) — an admin is the one exception, and sees everyone's,
because an admin who could not see a clinician's participants could not administer the account
that owns them. Every mutation writes an audit entry (E8).

**Endpoint-list note:** the plan of record's frozen API surface (§10) listed only
``GET /v1/participants/{pid}/calibration/active`` for this area; it omitted a create/list/edit
route despite B1/B2 both being Musts in the SRS. Confirmed with Enam (14 Aug 2026) that this was
an oversight in the plan document, not a deliberate exclusion — the plan of record has been
corrected in place rather than logged as a scope change.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.adapters.firestore_repo import COLLECTIONS, DocumentStore, get_document_store
from app.auth import CurrentUser, get_current_user
from app.domain import audit
from app.domain.ownership import load_owned_participant
from app.domain.participants import (
    AffectedSide,
    AgeBand,
    Participant,
    Sex,
    apply_edit,
    is_valid_code,
    new_participant,
    soft_delete,
)
from app.errors import ErrorCode, MyoLensError

router = APIRouter(prefix="/v1/participants", tags=["participants"])

_CODE_FIELD = Field(
    min_length=2,
    max_length=32,
    description="A pseudonymous code. Never a name — see app.domain.participants.",
)


class InvalidCode(MyoLensError):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message=(
                "The participant code must be 2-32 characters of letters, digits, '-' or '_', "
                "with no whitespace. It identifies a participant pseudonymously and must never "
                "be a name."
            ),
            details=[{"field": "code", "value": code}],
        )


class ParticipantCreate(BaseModel):
    code: str = _CODE_FIELD
    age_band: AgeBand
    sex: Sex
    affected_side: AffectedSide
    notes: str = Field(default="", max_length=2000)


class ParticipantEdit(BaseModel):
    """Every field optional: B2's "edit" only ever changes what the caller actually sent."""

    code: str | None = Field(default=None, min_length=2, max_length=32)
    age_band: AgeBand | None = None
    sex: Sex | None = None
    affected_side: AffectedSide | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ParticipantOut(BaseModel):
    id: str
    code: str
    age_band: AgeBand
    sex: Sex
    affected_side: AffectedSide
    notes: str
    created_by: str
    difficulty_band: str | None

    @staticmethod
    def from_domain(p: Participant) -> ParticipantOut:
        return ParticipantOut(
            id=p.id,
            code=p.code,
            age_band=p.age_band,
            sex=p.sex,
            affected_side=p.affected_side,
            notes=p.notes,
            created_by=p.created_by,
            difficulty_band=p.difficulty_band,
        )


StoreDep = Annotated[DocumentStore, Depends(get_document_store)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]


def _write_audit(store: DocumentStore, entry: audit.AuditEntry) -> None:
    store.set(COLLECTIONS.AUDIT, entry.id, entry.to_document())


@router.post("", response_model=ParticipantOut, status_code=201, summary="Register a participant")
def create_participant(body: ParticipantCreate, user: UserDep, store: StoreDep) -> ParticipantOut:
    if not is_valid_code(body.code):
        raise InvalidCode(body.code)

    participant = new_participant(
        code=body.code,
        age_band=body.age_band,
        sex=body.sex,
        affected_side=body.affected_side,
        notes=body.notes,
        created_by=user.uid,
    )
    store.set(COLLECTIONS.PARTICIPANTS, participant.id, participant.to_document())
    _write_audit(
        store,
        audit.record(
            actor=user.uid,
            action="participant.create",
            target_type="participant",
            target_id=participant.id,
            after=participant.to_document(),
        ),
    )
    return ParticipantOut.from_domain(participant)


@router.get("", response_model=list[ParticipantOut], summary="List my participants")
def list_participants(user: UserDep, store: StoreDep) -> list[ParticipantOut]:
    if user.role == "admin":
        docs = store.query(COLLECTIONS.PARTICIPANTS)
    else:
        docs = store.query(COLLECTIONS.PARTICIPANTS, createdBy=user.uid)
    # `query` returns bare documents with no id attached (see Participant.to_document); the id
    # travels as an ordinary field for exactly this reason.
    participants = [Participant.from_document(d["id"], d) for d in docs]
    return [ParticipantOut.from_domain(p) for p in participants if not p.is_deleted]


@router.get("/{participant_id}", response_model=ParticipantOut, summary="View one participant")
def get_participant(participant_id: str, user: UserDep, store: StoreDep) -> ParticipantOut:
    return ParticipantOut.from_domain(load_owned_participant(store, user, participant_id))


@router.patch("/{participant_id}", response_model=ParticipantOut, summary="Edit a participant")
def edit_participant(
    participant_id: str, body: ParticipantEdit, user: UserDep, store: StoreDep
) -> ParticipantOut:
    existing = load_owned_participant(store, user, participant_id)
    if body.code is not None and not is_valid_code(body.code):
        raise InvalidCode(body.code)

    updated = apply_edit(
        existing,
        code=body.code,
        age_band=body.age_band,
        sex=body.sex,
        affected_side=body.affected_side,
        notes=body.notes,
    )
    store.update(COLLECTIONS.PARTICIPANTS, participant_id, updated.to_document())
    _write_audit(
        store,
        audit.record(
            actor=user.uid,
            action="participant.update",
            target_type="participant",
            target_id=participant_id,
            before=existing.to_document(),
            after=updated.to_document(),
        ),
    )
    return ParticipantOut.from_domain(updated)


@router.delete(
    "/{participant_id}", response_model=ParticipantOut, summary="Soft-delete a participant"
)
def delete_participant(participant_id: str, user: UserDep, store: StoreDep) -> ParticipantOut:
    existing = load_owned_participant(store, user, participant_id)
    deleted = soft_delete(existing)
    store.update(COLLECTIONS.PARTICIPANTS, participant_id, deleted.to_document())
    _write_audit(
        store,
        audit.record(
            actor=user.uid,
            action="participant.delete",
            target_type="participant",
            target_id=participant_id,
            before=existing.to_document(),
            after=deleted.to_document(),
        ),
    )
    return ParticipantOut.from_domain(deleted)
