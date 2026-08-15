"""Ownership-scoped participant lookup (A3), shared by every router that needs "this
participant, if the caller is allowed to see them."

Pulled out of ``routers/participants.py`` so ``routers/calibrations.py`` (and every future
router keyed on a participant id — sessions, results) can enforce A3 the same way rather than
each re-implementing the not-found-vs-forbidden judgement call independently.
"""

from __future__ import annotations

from app.adapters.firestore_repo import COLLECTIONS, DocumentStore
from app.adapters.storage import ObjectStore, parse_object_name
from app.auth import CurrentUser
from app.config import get_settings
from app.domain.participants import Participant
from app.errors import InvalidUpload, NotFound, UploadTooLarge


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


def verify_upload_object(
    objects: ObjectStore,
    user: CurrentUser,
    object_name: str,
    participant_id: str,
    kind: str,
) -> None:
    """Refuse an object name that this caller was not given, for this participant, of this kind.

    ``object_name`` arrives as a plain string in a request body. Before this check it was passed
    straight to ``read_bytes``, which made it a request to read an arbitrary object in the
    bucket -- and because ``MontageRejected`` names the columns it actually found, a 409 on such
    a request disclosed the header row of whatever was named. Object names embed a ``uuid4``, so
    guessing another clinician's was infeasible in practice; "infeasible in practice" is not the
    answer one wants to give about an authorisation boundary that costs three comparisons.

    The byte ceiling is checked here too, before any download. D2's ten-minute cap is a
    *clinical* limit and can only be applied after the recording is decoded, so on its own it
    left the container committed to reading an object of any size into memory first.
    """
    try:
        parsed = parse_object_name(object_name)
    except ValueError as exc:
        raise InvalidUpload(str(exc)) from exc

    if parsed.kind != kind:
        raise InvalidUpload(f"this object was minted for a {parsed.kind} upload, not a {kind} one")

    # Same 404-for-both discipline as load_owned_participant: an object belonging to another
    # clinician is indistinguishable, to the caller, from one that does not exist.
    if parsed.owner_uid != user.uid:
        raise NotFound("recording", object_name)

    if parsed.participant_id != participant_id:
        raise InvalidUpload(
            "this object was minted for a different participant than the one named in the request"
        )

    max_bytes = get_settings().max_upload_bytes
    size = objects.size_bytes(object_name)
    if size is not None and size > max_bytes:
        raise UploadTooLarge(
            detail="the uploaded recording is larger than the maximum accepted size",
            max_bytes=max_bytes,
            actual_bytes=size,
        )
