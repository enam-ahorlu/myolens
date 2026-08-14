# ADR-004 — Authenticate at the application, not at the Cloud Run boundary

**Status** Accepted · **Date** in-window, Phase 2

## Context

The Cloud Run service is deployed `--allow-unauthenticated`, which reads alarmingly and deserves
an explicit justification rather than a shrug.

The client is a browser single-page application holding a Firebase ID token. The service needs to
know *which clinician* is calling in order to enforce that clinicians see only their own
participants (A3) and to attribute every audit entry to an actor (E8).

## Decision

Cloud Run IAM allows unauthenticated invocation. **Every route verifies a Firebase ID token in the
application**, and rejects an absent, expired or wrong-audience token with 401 (I2).

## Alternatives considered

**Cloud Run IAM authentication.** Rejected because it authenticates the wrong principal. IAM would
establish that *a Google identity* may invoke the service; it would say nothing about which
clinician is acting, so the application would still need to verify the Firebase token to enforce
A3 and attribute the audit log. It adds a second auth system that duplicates none of the work the
first one does, and makes browser calls substantially more awkward.

**An API gateway or load balancer doing token verification.** Rejected as scope. It is the right
answer at a larger scale, and it is a component this deployment does not otherwise need.

## Consequences

**Good.** One identity system, one place tokens are verified, and the identity that reaches the
domain layer is the one the audit log needs. Browser calls are ordinary `fetch` with a bearer
token.

**Bad, and mitigated rather than eliminated.** The service is publicly reachable, so every
unauthenticated request reaches the container before being rejected. The mitigations: token
verification runs before any handler; the only expensive route is rate-limited (I3); no route
leaks whether a participant exists to an unauthenticated caller; and logs carry no participant
identifiers (I4).

**Honest limit.** The rate limiter is in-process and Cloud Run runs up to three instances, so the
effective limit is up to three times the stated one. That is TD-07, and the register says "per
instance" rather than "per user" because the stronger claim would not survive being checked.

**Consequence for cost.** A public endpoint on a Blaze plan can be invoked by anyone.
`max-instances=3` is the ceiling that keeps that from becoming a bill.
