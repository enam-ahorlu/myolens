# Technical debt register

Classified on Fowler's quadrant (reckless/prudent × deliberate/inadvertent). Every item is tagged
in source as `TODO(TD-nn)`. **CI fails if an ID appears in source but not here, or here but not in
source** — see `scripts/check_satd.py`. The register is enforced by the build.

An item is only listed once it has a repayment plan. "We should improve this someday" is not debt;
it is an opinion.

| ID | Debt | Cause | Impact | Quadrant | Priority | Repayment |
|---|---|---|---|---|---|---|
| ~~TD-01~~ | ~~No held-out validation set~~ | — | — | — | — | **Resolved before the window.** Deployment models retrained on 37 of 40 subjects; subjects 10, 13 and 22 held out and used to verify deployed accuracy independently. |
| TD-02 | No live streaming inference | No hardware, and the causal normaliser is a measurably different regime (0.817 vs 0.858 macro-F1) | Offline batch analysis only | Prudent & Deliberate | Medium | v2.0, with a causal buffer and the causal figure quoted as the operating number |
| TD-03 | No multi-tenant isolation | 48-hour budget | Cannot serve two labs from one deployment | Prudent & Deliberate | High | v1.2, tenant-scoped Firestore rules and a tenant claim |
| TD-04 | Calibration statistics recomputed per request rather than cached | Caching needs an invalidation rule we have not designed | ~40 ms per assessment | Prudent & Deliberate | Medium | v1.1, cache keyed on `(participant_id, calibration_version)` |
| ~~TD-05~~ | ~~ONNX↔native equivalence unproven~~ | — | — | Reckless & Inadvertent | ~~Critical~~ | **Paid.** Max absolute delta 4.346e-07 over 200 windows, both models, 100% argmax agreement, in the serving runtime. Tolerance 1e-4 was not relaxed. Regression test ships in `backend/tests/`. |
| TD-06 | Demonstration fixtures double as test fixtures | Expedient — the held-out subjects were the cheapest realistic data available | Tests may encode fixture quirks rather than requirements | Prudent & Inadvertent | Low | v1.1, synthetic edge-case fixtures for the boundary conditions |
| TD-07 | Rate limiting is in-process, not distributed | Cloud Run scales to more than one instance; a shared counter needs Firestore or Redis | The 30/user/hour limit is per instance, so the effective limit is up to 3× the stated one | Prudent & Deliberate | Medium | v1.1, token bucket in Firestore with a transactional decrement |
| TD-08 | Audit log is client-immutable, not immutable | Firestore rules constrain clients; the Cloud Run service uses the Admin SDK and bypasses them | Server-side writes are unconstrained by rules; a compromised service could rewrite history | Prudent & Inadvertent | High | v1.1, object-versioned bucket mirror plus deny-delete IAM |

## On TD-08's wording

The log is **client-immutable**, not immutable, and the distinction is load-bearing. Firestore
security rules deny `update` and `delete` to every client, and there is a rules test that proves
it. The Cloud Run service authenticates with the Admin SDK, which bypasses rules entirely by
design. Claiming an immutable audit trail would therefore be one question away from being
dismantled in a viva. Saying what is actually true — clients cannot alter it, the server can, and
here is the plan to close that — is both accurate and defensible.

## On TD-05

TD-05 was the register's only Critical item and it was retired rather than deferred. One critical
debt actually paid is worth more than a register in which everything is comfortably scheduled for
a version that never ships. The equivalence test runs in CI on every commit.
