# Walking the deployed application as the examiner

Executed 15 August 2026, 18:35–19:00 UTC, in Chrome on Windows, signed in at
`https://myolens.web.app` as `examiner@myolens.test` — the account and the browser an examiner
will use. Discharges **H4** (the journey from a clean sign-in), **B7** (the I5 breakpoints) and
**B6** (the usability pass).

The seeded demo data was already in place from the run recorded in
[`seed-run-2026-08-15.md`](seed-run-2026-08-15.md), so the application was not empty at sign-in.

## What the journey found

**Three defects, none of which any test level below this one could reach.** All three are fixed;
the commits are named against each.

### 1. No browser could upload anything — `f408fc3`

Choosing a recording and pressing Upload produced *"Session upload failed. Please try again."*
The preflight `OPTIONS` to `storage.googleapis.com` returned `200` with **no
`Access-Control-Allow-Origin` header**, so Chrome refused to send the `PUT` that follows it. The
bucket had no CORS configuration.

ADR-002 is what makes this reachable: the recording goes from the browser straight to the bucket,
which is the right decision for a capture of this size and makes the upload a cross-origin
request. A bucket has no CORS policy by default.

Every level below a real browser is blind to it. The unit and integration suites substitute a fake
object store. `scripts/seed_demo_data.py` and `scripts/run_uat.py` both upload from Python, which
has no same-origin policy — which is precisely why both passed, an hour earlier, through the
outage. The deploy job's signing probe checks that the route answers, not that the URL it hands
back is usable by the caller it was minted for.

**Seven green CI jobs, 261 backend tests, 89 front-end tests, and a clinician could not upload a
single file.** The fix applies `infra/storage-cors.json` on every deploy and then proves it, by
issuing a real preflight and failing the build unless the header comes back.

### 2. The file picker rejected every recording the product ships — `40cb646`

Both upload inputs were `accept=".csv,text/csv"`. The demo captures are all `.csv.gz`, so the
native picker greyed them out. Nothing else in the upload path disagreed: `contentTypeFor()` has
always read the extension and returned `application/gzip`, the signed URL is minted for that type,
and the API reads either. Only the picker — the one part no test touches, because no test opens a
native file dialog — had the older idea.

### 3. Two arrangement defects the suite cannot see — `78c1a40`

Every results card was headed *"Sit to stand Sit to stand"*: an unabbreviated `TaskBadge` renders
the label, and the heading printed it again beside it.

The approve control sat **above** the review table, so the operator met "Approve segmentation"
before scrolling to a single bout — on a product whose entire claim is that a human reviews the
segmentation before any metric exists. Nothing was broken; the reading order argued against the
design. Both are queries about arrangement rather than behaviour, which is why a suite that
queries by role passed over them.

## The journey, after the fixes — H4

| Step | Result |
|---|---|
| Sign in | Participants screen, three seeded participants listed |
| Open DEMO-010 | Four tasks shown Calibrated; links to Calibration and Session |
| Upload `demo_Sub10_session.csv.gz` | Registered: session `a9e3c5fe…`, 21.0 s, 40,320 samples, status `uploaded` |
| Run segmentation | 167 windows, **4 bouts, 3 flagged**, status `segmented` |
| Review | Timeline plus bout table; flagged first, then ascending confidence — 41%, 64%, 65%, then the verified 62% |
| Approve | *"Segmentation approved. Metrics and export can now be computed."*; controls disappear, table relabels itself "Approved segmentation · locked" |
| Metrics | Three tasks, each with bout count/duration, pre-correction confidence, correction rate, both CCIs with qualifying-window counts, and a nine-channel amp mean/peak/duty-cycle table |
| Download PDF report | `myolens-session-a9e3c5fe-….pdf`, 5,581 bytes, on disk |

The intended-use statement (F3) was present on every screen in the walk, and on the sign-in screen
before authentication.

## Breakpoints — B7

Measured by rendering the application in fixed-width frames and reading
`scrollWidth` against `clientWidth`, which is the question "does this overflow" asked directly
rather than judged by eye.

| Width | Horizontal overflow | Notes |
|---|---|---|
| 768 px | none | Two-column layout holds; the intended-use banner wraps to three lines |
| 900 px | none | |
| 1024 px | none | |

The widest thing in the product is the per-channel metrics table. Its **min-content width is
673 px** against roughly 688 px of content column at 768 px — it fits, with about 15 px to spare.
That is a true pass and a thin one, and it is the number to re-check if a column is ever added to
that table.

## Usability — B6

Fixed in `78c1a40`: the doubled task heading, and the approve control preceding the bouts.

**Raised during the walk, and fixed the same evening: an existing session could not be reached
from the interface.** The frozen API surface (§10) had no route that listed or fetched a session,
so `SessionPage` held one session as client-side state from the moment it was created. A seeded,
approved session — with its bouts, its metrics and its PDF — was invisible to a clinician who did
not upload it in that browser tab. Worse than a navigation gap: **E3 is a Must whose acceptance
criterion is the single word "Persists,"** and a relabel did persist, into Firestore, where nothing
could observe it. Close the tab and the correction was gone for good.

It was raised rather than implemented on the spot, because adding a route touches the frozen-scope
claim and that is not a call to make quietly. On review it is the same omission as the participants
one corrected on 14 August, one layer down: §10 already listed **two** GETs keyed by a session id —
metrics and export — and nothing that would ever yield one. A list that consumes an identifier it
cannot produce is internally inconsistent, not deliberately minimal.

`MyoLens_PLAN_OF_RECORD.md` §10 was therefore corrected in place, to eighteen endpoints, with the
reasoning recorded there. `GET /v1/sessions/{sid}` returns the exact shape `POST .../segment`
already returned; `GET /v1/participants/{pid}/sessions` returns the session records the API was
already writing. Neither computes, decides or exposes anything new, and both are scoped by the
owning participant, so A3 is enforced where it always was. The participant page now lists a
participant's recordings, and `/participants/:id/session/:sessionId` reopens one.

Two consequences still carry into the writing phase:

- The **User Manual** should still show the examiner how to upload
  `backend/artifacts/demo/demo_Sub10_session.csv.gz` themselves. Watching segmentation happen is a
  better demonstration than reading someone else's result — the difference now is that it is a
  choice rather than the only option.
- **Maintenance & Future Evolution** has a worked example to hand: a requirement whose acceptance
  criterion no route could test, found by using the product rather than by reading it.
