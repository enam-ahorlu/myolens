"""The audit trail (E8, schema ``audit/{aid}``).

Every mutation writes one entry here, attributed to the actor who caused it. This module builds
the entry as an ordinary Python object; the adapter layer decides how it becomes a Firestore
write, same as everything else in ``app.domain`` (see TD-08 in ``firestore_repo.py`` for the
honest limit on how immutable this log actually is once it reaches Firestore).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class AuditEntry:
    id: str
    actor: str
    action: str
    target_type: str
    target_id: str
    at: datetime
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "action": self.action,
            "targetType": self.target_type,
            "targetId": self.target_id,
            "at": self.at.isoformat(),
            "before": self.before,
            "after": self.after,
        }


def record(
    *,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEntry:
    return AuditEntry(
        id=str(uuid4()),
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        at=datetime.now(UTC),
        before=before,
        after=after,
    )
