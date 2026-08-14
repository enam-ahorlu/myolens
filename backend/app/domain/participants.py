"""Participant records — pseudonymous by construction (B1), scoped to the clinician who created
them (A3), soft-deleted rather than destroyed (B2).

No field defined here, in the request schema, or in the Firestore document can hold a
participant's name. That is not a validation rule someone could route around — it is the absence
of a field to write to. *Won't:* clinical history, diagnosis codes, medication, consent uploads,
photographs (SRS §4.2 B).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class AgeBand(StrEnum):
    UNDER_18 = "under_18"
    Y18_29 = "18_29"
    Y30_44 = "30_44"
    Y45_59 = "45_59"
    Y60_74 = "60_74"
    Y75_PLUS = "75_plus"


class Sex(StrEnum):
    FEMALE = "female"
    MALE = "male"
    OTHER = "other"
    UNDISCLOSED = "undisclosed"


class AffectedSide(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    BILATERAL = "bilateral"
    NONE = "none"


#: A pseudonymous code, not a name: alphanumeric plus `-`/`_`, 2-32 characters, no whitespace.
#: Loose enough to admit a clinic's own coding scheme; tight enough to reject "Jane Doe" on sight.
CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$"
_CODE_RE = re.compile(CODE_PATTERN)


def is_valid_code(code: str) -> bool:
    return bool(_CODE_RE.fullmatch(code))


@dataclass(frozen=True)
class Participant:
    """The domain object. Firestore document shape lives only in ``to_document``/``from_document``
    — nothing above the adapter boundary knows the field names are camelCase there."""

    id: str
    code: str
    age_band: AgeBand
    sex: Sex
    affected_side: AffectedSide
    notes: str
    created_by: str
    created_at: datetime
    deleted_at: datetime | None = None
    difficulty_band: str | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def owned_by(self, uid: str) -> bool:
        return self.created_by == uid

    def to_document(self) -> dict[str, Any]:
        return {
            # Included even though the id is also the Firestore document id, because
            # ``DocumentStore.query`` (unlike ``get``) returns bare documents with no id attached
            # — see the discussion in ``routers/participants.py``. Duplicating it here is cheaper
            # than widening the adapter protocol for one caller.
            "id": self.id,
            "code": self.code,
            "ageBand": self.age_band.value,
            "sex": self.sex.value,
            "affectedSide": self.affected_side.value,
            "notes": self.notes,
            "createdBy": self.created_by,
            "createdAt": self.created_at.isoformat(),
            "deletedAt": self.deleted_at.isoformat() if self.deleted_at else None,
            "difficultyBand": self.difficulty_band,
        }

    @staticmethod
    def from_document(doc_id: str, doc: dict[str, Any]) -> Participant:
        deleted_at = doc.get("deletedAt")
        return Participant(
            id=doc.get("id") or doc_id,
            code=doc["code"],
            age_band=AgeBand(doc["ageBand"]),
            sex=Sex(doc["sex"]),
            affected_side=AffectedSide(doc["affectedSide"]),
            notes=doc.get("notes") or "",
            created_by=doc["createdBy"],
            created_at=datetime.fromisoformat(doc["createdAt"]),
            deleted_at=datetime.fromisoformat(deleted_at) if deleted_at else None,
            difficulty_band=doc.get("difficultyBand"),
        )


def new_participant(
    *,
    code: str,
    age_band: AgeBand,
    sex: Sex,
    affected_side: AffectedSide,
    notes: str,
    created_by: str,
) -> Participant:
    return Participant(
        id=str(uuid4()),
        code=code,
        age_band=age_band,
        sex=sex,
        affected_side=affected_side,
        notes=notes,
        created_by=created_by,
        created_at=datetime.now(UTC),
    )


def apply_edit(
    participant: Participant,
    *,
    code: str | None = None,
    age_band: AgeBand | None = None,
    sex: Sex | None = None,
    affected_side: AffectedSide | None = None,
    notes: str | None = None,
) -> Participant:
    """B2 edit: only the fields a caller actually supplied change. ``id``, ``created_by``,
    ``created_at`` and ``deleted_at`` are never touched by an edit — soft-delete is a separate
    operation with its own audit action, not a field an edit can quietly flip."""
    updates: dict[str, Any] = {}
    if code is not None:
        updates["code"] = code
    if age_band is not None:
        updates["age_band"] = age_band
    if sex is not None:
        updates["sex"] = sex
    if affected_side is not None:
        updates["affected_side"] = affected_side
    if notes is not None:
        updates["notes"] = notes
    return replace(participant, **updates)


def soft_delete(participant: Participant) -> Participant:
    return replace(participant, deleted_at=datetime.now(UTC))
