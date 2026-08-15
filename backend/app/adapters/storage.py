"""Cloud Storage access (ADR-002).

Every large upload (a calibration or session recording) goes to the bucket directly from the
browser via a V4 signed URL; the API never buffers the body. This module is the only place
that knows the bucket exists — same discipline as ``firestore_repo.py`` for Firestore.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from uuid import uuid4

from app.config import get_settings

#: Signed URLs are scoped to one object and expire quickly — long enough for a browser to
#: start a large upload, short enough that a leaked URL is not a standing credential.
SIGNED_URL_TTL_SECONDS = 900

#: The character set every path segment of an object name is restricted to. Deliberately
#: excludes ``/`` and ``.`` so a caller-supplied participant id cannot introduce a segment
#: boundary or an extension of its own.
_SEGMENT = r"[A-Za-z0-9_-]"

#: ``{kind}/{owner_uid}/{participant_id}/{uuid4}.csv`` — see ``new_object_name``.
OBJECT_NAME_PATTERN = re.compile(
    rf"^(?P<kind>calibration|session)"
    rf"/(?P<owner_uid>{_SEGMENT}{{1,128}})"
    rf"/(?P<participant_id>{_SEGMENT}{{1,64}})"
    rf"/(?P<token>{_SEGMENT}{{1,64}})\.csv$"
)


@dataclass(frozen=True)
class ObjectName:
    """The decomposition of an object name, so a router can check who it belongs to."""

    kind: str
    owner_uid: str
    participant_id: str
    token: str


def parse_object_name(object_name: str) -> ObjectName:
    """Decompose an object name, or raise :class:`ValueError`.

    Callers hand back an object name they were given by ``POST /v1/uploads/sign``. Nothing about
    that round trip is trustworthy on its own -- the field is a string in a request body, and
    without this parse it was previously passed straight to ``read_bytes``. Two consequences
    followed, both closed here and both checked by the routers rather than by this function:

    1. Any object in the bucket could be named and read. The montage validator names the columns
       it actually found in its 409 response, which turned that into a disclosure oracle for the
       first line of an arbitrary object.
    2. An object could be registered against a participant other than the one it was minted for.

    This function establishes the *shape*; ``owner_uid`` and ``participant_id`` are what the
    routers compare against the caller and the request body.
    """
    match = OBJECT_NAME_PATTERN.match(object_name)
    if match is None:
        raise ValueError(
            "object_name must be the value returned by POST /v1/uploads/sign, of the form "
            "{kind}/{uid}/{participant_id}/{token}.csv"
        )
    return ObjectName(**match.groupdict())


class ObjectStore(Protocol):
    """The narrow slice of object storage this application needs."""

    def signed_upload_url(self, object_name: str, content_type: str) -> str: ...
    def read_bytes(self, object_name: str) -> bytes: ...
    def size_bytes(self, object_name: str) -> int | None: ...


class GcsObjectStore:
    """``ObjectStore`` backed by real Google Cloud Storage."""

    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage  # deferred: see FirestoreDocumentStore's rationale

        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    def signed_upload_url(self, object_name: str, content_type: str) -> str:
        blob = self._bucket.blob(object_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=SIGNED_URL_TTL_SECONDS,
            method="PUT",
            content_type=content_type,
        )

    def read_bytes(self, object_name: str) -> bytes:
        blob = self._bucket.blob(object_name)
        return blob.download_as_bytes()

    def size_bytes(self, object_name: str) -> int | None:
        """The object's size without downloading it, or ``None`` if it cannot be determined.

        ``reload()`` is a metadata request, not a data transfer, which is the entire point: the
        duration cap (D2) was previously enforced only *after* the whole object had been pulled
        into memory and parsed, so a caller could commit the container to an arbitrarily large
        download before anything checked it. ``None`` on a missing object rather than raising --
        the subsequent ``read_bytes`` will produce the real error, and this method's job is to
        answer a size question, not to decide that an object does not exist.
        """
        blob = self._bucket.blob(object_name)
        try:
            blob.reload()
        except Exception:
            return None
        return blob.size


def new_object_name(kind: str, owner_uid: str, participant_id: str) -> str:
    """``{kind}/{owner_uid}/{participant_id}/{uuid4}.csv`` — collision-proof, and bound to the
    clinician who minted it.

    The owner segment is what makes the name self-authorising: registering an object requires
    only the name, so without it the name proves nothing about who is entitled to read the
    object. Putting the uid *in* the path keeps that check stateless -- no pending-upload record
    to write at signing time, nothing to expire, and no second round trip -- at the cost of
    encoding a clinician identifier in a bucket key, which is already recorded in ``createdBy``
    on every document the upload produces.

    The participant id remains in the path for the same reason it always was: it groups a
    participant's uploads. It is pseudonymous (``app.domain.participants``), so it is not a
    re-identification surface, and it is now also *checked* against the request body rather than
    merely being decorative.
    """
    return f"{kind}/{owner_uid}/{participant_id}/{uuid4()}.csv"


@lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    """FastAPI dependency: the process-wide store. Tests override this via
    ``app.dependency_overrides``, exactly like ``get_document_store``."""
    settings = get_settings()
    return GcsObjectStore(settings.storage_bucket)


__all__ = [
    "OBJECT_NAME_PATTERN",
    "SIGNED_URL_TTL_SECONDS",
    "GcsObjectStore",
    "ObjectName",
    "ObjectStore",
    "get_object_store",
    "new_object_name",
    "parse_object_name",
]
