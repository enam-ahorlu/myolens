"""Rate limiting, including the honest statement of what it does not guarantee."""

from __future__ import annotations

from app.middleware.rate_limit import InProcessRateLimiter


def test_requests_are_allowed_up_to_the_limit_then_refused():
    limiter = InProcessRateLimiter(limit_per_hour=3)

    assert [limiter.check("user")[0] for _ in range(3)] == [True, True, True]
    assert limiter.check("user")[0] is False


def test_the_window_slides():
    limiter = InProcessRateLimiter(limit_per_hour=2)
    limiter.check("user", now=0.0)
    limiter.check("user", now=1.0)

    assert limiter.check("user", now=2.0)[0] is False
    assert limiter.check("user", now=3601.0)[0] is True


def test_users_are_limited_independently():
    limiter = InProcessRateLimiter(limit_per_hour=1)
    assert limiter.check("a")[0] is True
    assert limiter.check("b")[0] is True
    assert limiter.check("a")[0] is False


def test_two_limiters_do_not_share_state():
    """Documents TD-07 as a test rather than only as a comment: two Cloud Run instances are two
    of these objects, so the honest guarantee is 'per instance', not 'per user'."""
    first = InProcessRateLimiter(limit_per_hour=1)
    second = InProcessRateLimiter(limit_per_hour=1)

    assert first.check("user")[0] is True
    assert second.check("user")[0] is True
