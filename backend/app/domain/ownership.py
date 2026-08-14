"""Ownership-scoped participant lookup (A3), shared by every router that needs "this
participant, if the caller is allowed to see them."

Pulled out of ``routers/participants.py`` so ``routers/calibrations.py`` (and every future
router keyed on a participant id — sessions, results) can enforce A3 the same way rather than
each re-implementing the not-found-vs-forbidden judgement call independently.
"""

from __future__ import annotations

from app.adapters.firestore_repo import COLLECTIONS, DocumentStore
from app.auth import CurrentUser
from app.domain.participants import Participant
from app.errors import NotFound


def load_owned_participant(
    store: DocumentStore, user: CurrentUser, participant_id: str
) -> Participant:
    """Fetch a participant, or raise :class:`NotFound` for absent, soft-deleted, or not-mine.

    Cross-clinician access and a nonexistent id get the identical 404 (see the docstring on
    ``errors.NotFound``) — the same reasoning ADR-004 applies to unauthenticated callers,
    extended here to authenticated non-owners.
    """
    doc = store.get(COLLECTIONS.PARTICIPANTS, participant_id)
    if doc is None:
        raise NotFound("participant", participant_id)
    participant = Participant.from_document(participant_id, doc)
    if participant.is_deleted:
        raise NotFound("participant", participant_id)
    if user.role != "admin" and not participant.owned_by(user.uid):
        raise NotFound("participant", participant_id)
    return participant
