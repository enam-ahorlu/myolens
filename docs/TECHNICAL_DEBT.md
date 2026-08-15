# Technical debt register

Classified on Fowler's quadrant (reckless/prudent × deliberate/inadvertent). Every item is tagged
in source as `TODO(TD-nn)`. **CI fails if an ID appears in source but not here, or here but not in
source** — see `scripts/check_satd.py`. The register is enforced by the build.

An item is only listed once it has a repayment plan. "We should improve this someday" is not debt;
it is an opinion.

| ID | Debt | Cause | Impact | Quadrant | Class | Priority | Repayment |
|---|---|---|---|---|---|---|---|
| ~~TD-01~~ | ~~No held-out validation set~~ | — | — | — | ~~Critical~~ | — | **Resolved before the window.** Deployment models retrained on 37 of 40 subjects; subjects 10, 13 and 22 held out and used to verify deployed accuracy independently. |
| TD-02 | No live streaming inference | No hardware, and the causal normaliser is a measurably different regime (0.817 vs 0.858 macro-F1) | Offline batch analysis only | Prudent & Deliberate | **Acceptable temporarily** | Medium | v2.0, with a causal buffer and the causal figure quoted as the operating number |
| TD-03 | No multi-tenant isolation | 48-hour budget | Cannot serve two labs from one deployment | Prudent & Deliberate | **Scheduled** | High | v1.2, tenant-scoped Firestore rules and a tenant claim |
| TD-04 | Calibration statistics recomputed per request rather than cached | Caching needs an invalidation rule we have not designed | ~40 ms per assessment | Prudent & Deliberate | **Acceptable temporarily** | Medium | v1.1, cache keyed on `(participant_id, calibration_version)` |
| ~~TD-05~~ | ~~ONNX↔native equivalence unproven~~ | — | — | Reckless & Inadvertent | ~~Critical~~ | ~~Critical~~ | **Paid.** Max absolute delta 4.346e-07 over 200 windows, both models, 100% argmax agreement, in the serving runtime. Tolerance 1e-4 was not relaxed. Regression test ships in `backend/tests/`. |
| TD-06 | Demonstration fixtures double as test fixtures, **and now as the measurement set for a reported result** | Expedient — the held-out subjects were the cheapest realistic data available | Tests may encode fixture quirks rather than requirements, and D6's published bout-coherence figures inherit any such quirk | Prudent & Inadvertent | **Scheduled** | ~~Low~~ **Medium** | v1.1, synthetic edge-case fixtures for the boundary conditions, and an independent set for any figure that is reported rather than merely asserted |
| TD-07 | Rate limiting is in-process, not distributed | Cloud Run scales to more than one instance; a shared counter needs Firestore or Redis | The 30/user/hour limit is per instance, so the effective limit is up to 3× the stated one | Prudent & Deliberate | **Scheduled** | Medium | v1.1, token bucket in Firestore with a transactional decrement |
| TD-08 | Audit log is client-immutable, not immutable | Firestore rules constrain clients; the Cloud Run service uses the Admin SDK and bypasses them | Server-side writes are unconstrained by rules; a compromised service could rewrite history | Prudent & Inadvertent | **Scheduled** | High | v1.1, object-versioned bucket mirror plus deny-delete IAM |
| TD-09 | No automated browser-level test | The acceptance suite drives the API over HTTP from Python, which is fast, deterministic and free of a same-origin policy | Two production defects reached the deployment because every automated caller shared that blind spot: the bucket's missing CORS policy and the upload picker's file filter. Both were found by hand | Prudent & Inadvertent | **Scheduled** | High | v1.1, a Playwright suite in CI covering sign-in, calibration upload, segmentation, correction, approval and export against a preview deployment |

## On the classification column

Part A §7 of the examination asks debt to be distinguished as *acceptable temporarily*,
*scheduled for future resolution*, or *critical and requiring immediate attention*. That axis is
not the same question as Fowler's quadrant, so both are kept: the quadrant says how the debt was
*incurred* (was the decision deliberate, was it prudent), and the class says what is being *done*
about it. A prudent, deliberate item can be either acceptable or scheduled depending on whether
anything is actually planned, and conflating the two would hide exactly that distinction.

**The register currently holds no Critical item, and that is a result rather than an absence.**
It held exactly one — TD-05, ONNX↔native equivalence unproven — and it was paid inside the window
rather than reclassified downward or deferred to a version that never ships. An empty Critical row
earned that way is worth more than a register where everything is comfortably Medium.

## On TD-06's re-evaluation

TD-06 was raised from Low to Medium after the held-out three acquired a third and fourth role.
They began as an independent validation set for the deployed models and as demonstration
recordings; they are now also the fixtures several tests assert against, **and** the measurement
set behind D6's reported bout-coherence figures (130 → 17 bouts, 14% → 50% cleanly recovered).

Four roles on one dataset is one too many. The specific exposure is not that any current number
is wrong — it is that a quirk of these three subjects would propagate into a *published* figure
with nothing independent to catch it, and n = 3 is far too small for that to be unlikely. The
figures are therefore reported as indicative, exactly as held-out accuracy is (SRS §6), and the
repayment now names an independent set for anything reported rather than merely asserted.

## On TD-09

TD-09 was raised on 15 August, after the browser walkthrough found two defects that no automated
caller could have found. The acceptance suite uploads from Python, and Python has no same-origin
policy, so it passed cleanly through an outage in which no browser could upload anything at all.
The file picker's `accept` filter is invisible to it for the same reason: nothing in the suite
opens a native file dialog.

The exposure is specific. Every requirement whose behaviour lives between the browser and an
external service is currently verified by a person doing it once, and a person doing it once does
not run again on the next push. The single preflight assertion added to the deploy job covers the
one failure that actually happened, and nothing covers the class it belongs to.

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
