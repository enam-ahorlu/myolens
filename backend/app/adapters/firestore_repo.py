"""Firestore access.

Every read and write to Firestore passes through this module. Nothing above the adapter layer
knows that Firestore exists, which is what keeps the domain testable without an emulator and
what would make a store migration a rewrite of one file rather than of the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from app.config import get_settings


class DocumentStore(Protocol):
    """The narrow slice of a document database this application actually needs.

    ``delete`` was added for segmentation review's bout merge (E5): merging two bouts removes
    one of the two original documents rather than leaving an orphan behind. Every other
    mutation in this codebase is add-or-update by design (soft-delete for participants, C5's
    supersede-never-overwrite for calibrations); this is the one genuine case where a document
    must actually stop existing, so the protocol grew to cover it rather than working around
    its absence with a tombstone field.
    """

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...
    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...
    def update(self, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...
    def delete(self, collection: str, doc_id: str) -> None: ...
    def query(self, collection: str, **filters: Any) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class Collections:
    """Collection names in one place, so a typo is a NameError rather than an empty result set."""

    USERS: str = "users"
    PARTICIPANTS: str = "participants"
    SESSIONS: str = "sessions"
    MODELS: str = "models"
    AUDIT: str = "audit"

    # These three are top-level collections, keyed by a parent id held in a field
    # (participantId / sessionId), not Firestore subcollections. They were described as
    # subcollections here, which was wrong in a way that mattered: firestore.rules matches
    # /bouts/{boutId}, so a reader trusting the comment would have looked for the rule in the
    # wrong place -- or, worse, "corrected" the code to match the comment and silently moved the
    # data out from under the rule that protects it. test_firestore_integration.py asserts the
    # application writes where the rules look.
    CALIBRATIONS: str = "calibrations"
    BOUTS: str = "bouts"
    METRICS: str = "metrics"


COLLECTIONS = Collections()


class FirestoreDocumentStore:
    """``DocumentStore`` backed by real Google Cloud Firestore.

    The only class in this codebase that imports ``google.cloud.firestore``. Constructed once per
    process (see :func:`get_document_store`) and held for the life of the container; the client
    is safe to share across requests.
    """

    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore  # deferred: keeps `firestore_repo` importable, and

        # every test importable, without network credentials on the path.
        self._client = firestore.Client(project=project) if project else firestore.Client()

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        snapshot = self._client.collection(collection).document(doc_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        self._client.collection(collection).document(doc_id).set(data)

    def update(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        self._client.collection(collection).document(doc_id).update(data)

    def delete(self, collection: str, doc_id: str) -> None:
        self._client.collection(collection).document(doc_id).delete()

    def query(self, collection: str, **filters: Any) -> list[dict[str, Any]]:
        ref: Any = self._client.collection(collection)
        for field, value in filters.items():
            ref = ref.where(field, "==", value)
        return [doc.to_dict() for doc in ref.stream()]


@lru_cache(maxsize=1)
def get_document_store() -> DocumentStore:
    """FastAPI dependency: the process-wide store. Tests override this via
    ``app.dependency_overrides``, so it is never actually called — and therefore never actually
    opens a network connection — outside a running deployment."""
    settings = get_settings()
    return FirestoreDocumentStore(project=settings.gcp_project_id or None)


# TODO(TD-03): there is no tenant scoping anywhere in this module or in the security rules.
# Prudent & deliberate. Real multi-tenancy means a tenant claim on every token, a tenant field on
# every document, and rules that enforce it on every path — and a half-implemented version that
# looks isolated but is not would be considerably worse than an honest single-tenant deployment.
# Impact: one laboratory per deployment. Priority: High.
# Repayment: v1.2, tenant claim plus tenant-scoped rules, with a rules test per collection.

# TODO(TD-08): the audit log is client-immutable, not immutable.
# Prudent & inadvertent — the gap was understood only once the rules were written. Firestore
# rules deny update and delete to every client and a rules test proves it, but this service
# authenticates with the Admin SDK, which bypasses rules by design. So a compromised or buggy
# service could rewrite history, and describing the log as immutable would be one question away
# from being dismantled.
# Impact: server-side writes are unconstrained. Priority: High.
# Repayment: v1.1, mirror every audit entry to an object-versioned bucket with deny-delete IAM,
# so the authoritative copy is outside this service's authority.
