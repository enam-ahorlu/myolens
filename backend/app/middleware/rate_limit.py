"""Inference rate limiting.

Segmentation is the only genuinely expensive operation in this system: a ten-minute recording is
roughly 4,800 windows through a 72-feature extractor and two ONNX graphs. Left unbounded, a
scripted client could run the container's cost up without ever authenticating as anyone unusual.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from functools import lru_cache

from app.config import get_settings


class InProcessRateLimiter:
    """Sliding-window rate limiter, per user, held in process memory."""

    def __init__(self, limit_per_hour: int) -> None:
        self.limit = limit_per_hour
        self.window_seconds = 3600
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, user_id: str, now: float | None = None) -> tuple[bool, int]:
        """Return ``(allowed, remaining)`` and record the hit when allowed."""
        current = time.monotonic() if now is None else now
        hits = self._hits[user_id]
        cutoff = current - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return False, 0
        hits.append(current)
        return True, self.limit - len(hits)


@lru_cache(maxsize=1)
def get_rate_limiter() -> InProcessRateLimiter:
    """Process-wide singleton (I3), overridable in tests via FastAPI's dependency-override
    mechanism -- the same discipline ``get_document_store``/``get_object_store`` use."""
    return InProcessRateLimiter(limit_per_hour=get_settings().rate_limit_per_hour)


# TODO(TD-07): this limiter is per process, and Cloud Run runs up to three instances.
# Prudent & deliberate. A correct implementation needs a shared transactional counter; an
# in-process one was affordable and closes the trivial abuse case. The honest statement of the
# guarantee is therefore "at least 30 per hour per instance", not "30 per hour" — which is why
# the number is documented as an approximate ceiling rather than a contract.
# Impact: effective limit is up to 3x the stated one. Priority: Medium.
# Repayment: v1.1, token bucket in Firestore with a transactional decrement.
