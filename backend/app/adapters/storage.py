"""Cloud Storage access (ADR-002).

Every large upload (a calibration or session recording) goes to the bucket directly from the
browser via a V4 signed URL; the API never buffers the body. This module is the only place
that knows the bucket exists — same discipline as ``firestore_repo.py`` for Firestore.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol
from uuid import uuid4

from app.config import get_settings

#: Signed URLs are scoped to one object and expire quickly — long enough for a browser to
#: start a large upload, short enough that a leaked URL is not a standing credential.
SIGNED_URL_TTL_SECONDS = 900


class ObjectStore(Protocol):
    """The narrow slice of object storage this application needs."""

    def signed_upload_url(self, object_name: str, content_type: str) -> str: ...
    def read_bytes(self, object_name: str) -> bytes: ...


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


def new_object_name(kind: str, participant_id: str, extension: str = "csv") -> str:
    """``{kind}/{participant_id}/{uuid}.{extension}`` — collision-proof, and groups a
    participant's uploads together without ever encoding anything identifying in the name
    itself (the id is already pseudonymous, per app.domain.participants)."""
    return f"{kind}/{participant_id}/{uuid4()}.{extension}"


@lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    """FastAPI dependency: the process-wide store. Tests override this via
    ``app.dependency_overrides``, exactly like ``get_document_store``."""
    settings = get_settings()
    return GcsObjectStore(settings.storage_bucket)


__all__ = [
    "SIGNED_URL_TTL_SECONDS",
    "GcsObjectStore",
    "ObjectStore",
    "get_object_store",
    "new_object_name",
]
