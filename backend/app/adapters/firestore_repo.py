"""Firestore access.

Every read and write to Firestore passes through this module. Nothing above the adapter layer
knows that Firestore exists, which is what keeps the domain testable without an emulator and
what would make a store migration a rewrite of one file rather than of the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class DocumentStore(Protocol):
    """The narrow slice of a document database this application actually needs."""

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...
    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...
    def update(self, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...
    def query(self, collection: str, **filters: Any) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class Collections:
    """Collection names in one place, so a typo is a NameError rather than an empty result set."""

    USERS: str = "users"
    PARTICIPANTS: str = "participants"
    SESSIONS: str = "sessions"
    MODELS: str = "models"
    AUDIT: str = "audit"

    CALIBRATIONS: str = "calibrations"  # subcollection of a participant
    BOUTS: str = "bouts"                # subcollection of a session
    METRICS: str = "metrics"            # single document under a session


COLLECTIONS = Collections()

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
