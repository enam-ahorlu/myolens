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
    """Sliding-window rate limiter, per user *per bucket*, held in process memory.

    Buckets exist because the routes worth limiting are not equally expensive and must not share
    a quota. Segmentation is the costly one (I3) and gets the tight ceiling; registering a
    recording is cheaper but commits the container to a download and a parse; minting a signed
    URL is nearly free server-side but authorises a bucket write. Putting all three on one
    counter would mean a clinician who uploaded a lot of recordings could no longer segment any
    of them, which is the wrong failure.
    """

    def __init__(self, limit_per_hour: int, limits: dict[str, int] | None = None) -> None:
        self.limit = limit_per_hour
        self.window_seconds = 3600
        self._limits = limits or {}
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def limit_for(self, bucket: str) -> int:
        return self._limits.get(bucket, self.limit)

    def check(
        self, user_id: str, bucket: str = "segment", now: float | None = None
    ) -> tuple[bool, int]:
        """Return ``(allowed, remaining)`` and record the hit when allowed."""
        current = time.monotonic() if now is None else now
        limit = self.limit_for(bucket)
        hits = self._hits[(bucket, user_id)]
        cutoff = current - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            return False, 0
        hits.append(current)
        return True, limit - len(hits)


#: Bucket names, so a typo is an import error rather than a silently separate quota.
BUCKET_SEGMENT = "segment"
BUCKET_SESSION_CREATE = "session_create"
BUCKET_UPLOAD_SIGN = "upload_sign"


@lru_cache(maxsize=1)
def get_rate_limiter() -> InProcessRateLimiter:
    """Process-wide singleton (I3), overridable in tests via FastAPI's dependency-override
    mechanism -- the same discipline ``get_document_store``/``get_object_store`` use."""
    settings = get_settings()
    return InProcessRateLimiter(
        limit_per_hour=settings.rate_limit_per_hour,
        limits={
            BUCKET_SEGMENT: settings.rate_limit_per_hour,
            BUCKET_SESSION_CREATE: settings.session_create_rate_limit_per_hour,
            BUCKET_UPLOAD_SIGN: settings.upload_sign_rate_limit_per_hour,
        },
    )


# TODO(TD-07): this limiter is per process, and Cloud Run runs up to three instances.
# Prudent & deliberate. A correct implementation needs a shared transactional counter; an
# in-process one was affordable and closes the trivial abuse case. The honest statement of the
# guarantee is therefore "at least 30 per hour per instance", not "30 per hour" — which is why
# the number is documented as an approximate ceiling rather than a contract.
# Impact: effective limit is up to 3x the stated one. Priority: Medium.
# Repayment: v1.1, token bucket in Firestore with a transactional decrement.
