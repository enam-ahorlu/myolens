# Software Requirements Specification

**MyoLens — task-conditioned sEMG session analysis with reviewable automatic segmentation**

**Enam Ahorlu · CSCD602 Advanced Software Engineering · Individual Project Examination**
Version 1.0 · Baselined at the scope freeze

---

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements for MyoLens, a clinician-facing web application that
segments a multi-task lower-limb surface electromyography (sEMG) recording into movement bouts,
has a human review and correct that segmentation, and only then computes task-conditioned muscle
activation and co-activation metrics.

It is written for the examiner, for a clinical reader evaluating whether the system is safe to
use, and for the maintainer who will extend it. Section 5 is the one to read first: every
functional requirement is traced to a measurement, and most of those measurements are from the
author's own thesis.

### 1.2 Scope of the product

MyoLens **does**: register pseudonymous participants; accept a labelled calibration capture and
an unlabelled multi-task session recording; validate both against a fixed nine-channel montage;
propose a segmentation using a two-model ensemble; surface the least-certain bouts first for
human review; accept corrections; and, after explicit human approval, compute and export
task-conditioned amplitude, duty-cycle and co-contraction metrics.

MyoLens **does not**: classify in real time, drive any device, diagnose, recommend treatment, or
report any metric that has not been reviewed by a person. Section 4.3 lists the exclusions and
why each one is excluded.

### 1.3 The problem, and why this shape of solution

sEMG amplitude is only interpretable relative to the task being performed. A recording in which a
participant walks, climbs stairs, descends stairs and stands up from a chair therefore has to be
segmented by task before any metric computed from it means anything. In current practice that
segmentation is done by hand, and the literature on barriers to clinical sEMG names time cost and
specialist-expertise burden among the principal reasons the modality has not entered routine
practice, calling explicitly for "intelligent systems with warnings" and "fool-proof interfaces."

Automatic classification can remove most of that manual labour. It cannot remove the clinician,
and the reason is measurable rather than philosophical: the serving ensemble reaches a macro-F1 of
**0.858**, which leaves roughly one window in seven carrying the wrong label before smoothing, and
its weakest class — stair descent — sits at **F1 0.81** with a residual **6.6%** of descent windows
still read as level walking. Those figures describe *this* ensemble under *this* protocol. The
single classical models are markedly worse on the same boundary (12.5% for the SVM) and do not
describe what is deployed here; quoting their numbers against this system would be precisely the
regime error FR-09 and NFR-04 exist to prevent.

A system that computed metrics directly from unreviewed labels would therefore attribute part of
one task's activation to another, silently, with nothing in the output looking unusual. A system
that *proposes* a segmentation, orders the doubtful parts first, and computes nothing until a human
agrees converts the same model from an unreliable oracle into a competent first draft.

Two further reasons the human is not optional, and neither weakens if the model improves. The model
has never been evaluated on any clinical population (CON-6), so its error rate on the people a
clinic would actually record is unknown rather than merely small. And a metric computed from an
unreviewed segmentation is *unfalsifiable by the person reading it* — nothing in a `%CAL` figure
reveals which bouts produced it, so a reader has no way to notice that it is wrong.

### 1.4 Relationship to the author's thesis, and its limits

The classification models are prior work, disclosed in `DECLARATION.md`. The thesis is a
**prosthetic-control** thesis, and MyoLens is explicitly not a control system. What authorises
this application is §5.8.1 of that thesis, verbatim:

> *"And for less safety-critical applications, such as gait-phase monitoring, activity logging, or
> rehabilitation progress tracking, a macro F1 of around 80% across four classes may well be
> enough, especially once temporal smoothing or confidence thresholds are added to reject
> low-certainty predictions."*

MyoLens is that application, at that accuracy, and it exceeds the stated threshold rather than
merely meeting it: §5.8.1 conditions its claim on "around 80%", and the serving ensemble measures
0.858.

It implements the first of the two named mechanisms literally — temporal smoothing, FR-06, as a
5-window majority vote followed by per-class minimum dwell. **The second it substitutes rather
than implements, and the difference is stated here rather than glossed.** §5.8.1 contemplates
confidence thresholds that *reject* low-certainty predictions automatically; MyoLens instead routes
them to a person (FR-07, E2) and computes nothing at all until that person approves (FR-08).
Automatic rejection would silently discard the windows the model finds hardest, which in this
application are disproportionately stair descent — so a resting-on-thresholds system would quietly
under-report the one task a clinician is most likely to be interested in. Review discards nothing
and spends the clinician's attention on exactly those windows. The substitution is deliberate and
is claimed as stricter than the thesis's condition, not as identical to it.

No claim in this specification extends the thesis's findings beyond the population it measured.

### 1.5 Definitions

| Term | Meaning |
|---|---|
| **Bout** | A contiguous run of windows carrying the same task label after smoothing |
| **Window** | 480 samples (250 ms) of nine-channel signal, stepped 240 samples (125 ms) |
| **%CAL** | Amplitude as a percentage of the participant's own peak calibration envelope |
| **MVC** | Maximum voluntary contraction. **Not used** — see NFR-C2 |
| **Transductive** | Normalisation statistics computed over the whole recording being analysed |
| **Causal** | Normalisation statistics computed from past samples only |
| **OOD** | Out of distribution, relative to the model's training population |
| **Macro-F1** | F1 averaged equally over classes, so a rare class cannot be hidden by a common one |
| **LOSO** | Leave-one-subject-out cross-validation |
| **Montage** | The specific set, order and placement of electrode channels |

**Vocabulary discipline**, applied throughout the product and this document: *participant* not
patient · *export* not signed report · *analysis* or *assessment support* not clinical decision
support · *review priority* not safety.

---

## 2. Overall description

### 2.1 Product perspective

A new, self-contained system. React 19 single-page client on Firebase Hosting; FastAPI service on
Cloud Run; Cloud Firestore for records; Cloud Storage for recordings and per-window prediction
arrays; Firebase Authentication for identity. The classification models are consumed as frozen
ONNX graphs behind an internal `Predictor` interface, which is the seam at which a future model
attaches without changes above it.

### 2.2 Intended use statement

This statement ships in the product, on every screen and in every export.

> **MyoLens** is a research and clinical-education tool for analysing multi-task surface
> electromyography recordings. It proposes a segmentation of a recording into movement tasks,
> which the operator reviews and corrects, and then reports task-conditioned muscle activation and
> co-activation metrics computed on the approved segmentation.
>
> MyoLens is **not a medical device** and is **not intended for diagnosis, treatment, or clinical
> decision-making.** Its classification model was developed on recordings from 40 healthy adults
> (SIAT-LLMD; Wei et al., 2023) and has not been validated on any clinical population. It is
> intended for able-bodied and mildly-impaired ambulatory adults, using the specified nine-channel
> unilateral lower-limb montage only.
>
> Amplitude metrics are normalised to the participant's own within-session calibration reference
> (`%CAL`) and are **not** maximum-voluntary-contraction normalised. Amplitude values are not
> comparable across sessions.

### 2.3 Stakeholders

| Stakeholder | Interest | Served by |
|---|---|---|
| Clinical researcher / gait-lab scientist (**primary**) | Fast, reviewable task segmentation; defensible metrics | The whole workflow |
| Physiotherapist (**secondary**) | Task-conditioned activation and co-activation figures | Metrics, export |
| Participant (**indirect**) | Privacy; not being over-claimed about | Pseudonymisation, intended-use statement |
| Laboratory administrator | Account control, provenance | Roles, model registry, audit log |
| Ethics committee (**secondary**) | Traceability, honest performance claims | Audit trail, regime-labelled accuracy |
| Maintainer | Swap the model without rewriting the application | Model-serving boundary |

The participant is an *indirect* stakeholder who never touches the software, and whose interests
are therefore represented only by requirements someone else has to be prevented from bypassing —
which is why B1 (no name field exists), C4 (refusal) and F3 (banner) are Must and are on the
never-cut list.

### 2.4 Operating environment

Desktop or tablet browser at 768 px width and above. **Below 768 px is out of scope by decision,
not by omission**: the segmentation timeline is the core interaction and is unusable at phone
width, and a gait laboratory does not review recordings on a phone.

### 2.5 Constraints

| ID | Constraint | Consequence |
|---|---|---|
| CON-1 | Cloud Run caps HTTP/1 request bodies at 32 MB; nine channels at 2 kHz is ~9.7 MB per minute of CSV | A session cannot be POSTed. Uploads go direct to Cloud Storage via V4 signed URL (D1) |
| CON-2 | Training used scikit-learn on Python 3.14; the serving container is Python 3.12 | Models ship as ONNX, not pickles. A pickle would couple the container to a bleeding-edge stack and fail as a subtly wrong model rather than a clean error |
| CON-3 | Maximal-effort testing is contraindicated in the target populations | No MVC normalisation is possible; amplitudes are %CAL and not comparable across sessions |
| CON-4 | The montage is unilateral | Bilateral and symmetry metrics are **physically impossible**, not merely unimplemented |
| CON-5 | 48-hour development budget, one developer | Scope is the only free variable. See the effort estimation and the de-scope ladder |
| CON-6 | The model was trained on 40 healthy adults | Any clinical-population claim is unsupported. Generalisation is stated as unknown |

### 2.6 Assumptions

- Recordings are exported with the exact channel names and order in §3.1.
- The operator is a trained professional who can recognise a movement task from a signal trace.
- Accounts are provisioned by an administrator; there is no self-registration.
- The examiner's browser is a current Chrome, Edge or Firefox.

---

## 3. Frozen contracts

These three are baselined. A change to any of them is a change to the product, not to an
implementation detail, and requires an entry in `SCOPE_CHANGE_LOG.md`.

### 3.1 The montage contract

| # | Channel name (exact) | Group |
|---|---|---|
| 1 | `sEMG: tensor fascia lata` | Hip abductor |
| 2 | `sEMG: rectus femoris` | Knee extensor (**A**) |
| 3 | `sEMG: vastus medialis` | Knee extensor (**A**) |
| 4 | `sEMG: semimembranosus` | Knee flexor (**B**) |
| 5 | `sEMG: upper tibialis anterior` | Dorsiflexor (**C**) |
| 6 | `sEMG: lower tibialis anterior` | Dorsiflexor (**C**) |
| 7 | `sEMG: lateral gastrocnemius` | Plantarflexor (**D**) |
| 8 | `sEMG: medial gastrocnemius` | Plantarflexor (**D**) |
| 9 | `sEMG: soleus` | Plantarflexor (**D**) |

Sampled at 1920 Hz · band-pass 20–450 Hz, 4th order · 50 ms linear envelope · 250 ms window,
125 ms step · unilateral, side declared per session.

**Matching is by exact string equality. There is no fuzzy mapping.** A near-miss on a channel name
is more likely to be a different electrode placement than a typo, and the failure mode of guessing
is a silently mis-ordered montage: every metric computes cleanly, every number is wrong, and
nothing in the output looks unusual. Rejection is recoverable in thirty seconds; a silent
reordering is not recoverable at all, because nobody knows to look.

ENABL3S, the thesis's second corpus, is **not** shipped: seven channels at 1 kHz cannot satisfy
this contract. That exclusion is evidence the contract is enforced rather than declared.

> **Note on the sampling rate.** SIAT-LLMD's metadata reports 1920.0001344 Hz, and 480 / 1920 =
> 0.250 s exactly. Descriptions that round it to 2 kHz are wrong; the 250 ms window is what is
> authoritative. Separately, the frozen feature specification computes mean and median frequency
> against a hardcoded 2000 Hz, which makes that constant part of the model rather than a
> parameter. Per-column z-scoring absorbs the resulting 1.0417 scale factor exactly, so no
> classification result depends on it. MyoLens reports no frequency in hertz, so nothing
> user-facing is affected. Both constants are asserted by test.

### 3.2 The class set

`["DNS", "STDUP", "UPS", "WAK"]` — stair descent, sit-to-stand, stair ascent, level walking. The
order is frozen because it is the output order of both ONNX graphs. **No fifth class appears
anywhere in the product, including in empty states.**

### 3.3 The metric set

Computed **only** on an approved segmentation, per task, per session.

| Metric | Definition | Unit |
|---|---|---|
| `bout_count` | Approved bouts of this task | count |
| `bout_duration_total` | Summed approved bout duration | s |
| `amp_mean[ch]` | Mean envelope over the task's bouts ÷ participant's peak calibration envelope × 100 | %CAL |
| `amp_peak[ch]` | Peak, likewise | %CAL |
| `duty_cycle[ch]` | Share of windows above 15% of the participant's calibration peak | % |
| `CCI_knee` | Co-contraction, extensors (RF, VM) vs flexor (SM) | 0–100 |
| `CCI_ankle` | Co-contraction, dorsiflexors (TA×2) vs plantarflexors (LG, MG, SOL) | 0–100 |
| `model_confidence_mean` | Mean ensemble confidence, pre-correction | 0–1 |
| `correction_rate` | Share of windows whose label the operator changed | % |

**Co-contraction index, frozen formula** (Falconer & Winter form). For window *i*, with `A_i` the
mean %CAL envelope of the agonist group and `B_i` that of the antagonist group:

```
CCI = mean over qualifying windows( 2 · min(A_i, B_i) / (A_i + B_i) ) × 100
```

A window qualifies when at least one group exceeds 15% of calibration peak. Where **no** window
qualifies the result is **null, not zero** — at rest the ratio is still arithmetically defined and
is dominated entirely by the relative size of two noise floors, so a resting limb would otherwise
report as strongly co-contracting. Zero co-contraction is a clinical finding; no data is not.
This edge case is a named unit test.

The co-activation indices lead the report and raw amplitude is secondary. This is a deliberate
ordering: a CCI is a *ratio* of two simultaneous amplitudes, so the missing MVC anchor cancels,
whereas raw amplitude carries that absence directly.

---

## 4. Requirements

### 4.1 Traceability to evidence

The centrepiece of this specification. Every row's justification is a measurement, and the
"Evidence" column is what distinguishes a requirement from a preference.

| ID | Requirement | Type | Priority | Basis | Evidence |
|---|---|---|---|---|---|
| **FR-01** | Normalisation statistics shall be computed from the assessment session itself, over the whole recording | Functional | **Must** | Transductive per-subject z-scoring is the single dominant accuracy lever | SVM 70.8 → 77.7% macro-F1, +6.9 pp, p < 0.0001, d = 1.48; replicated on a second corpus at +10.3 pp |
| **FR-02** | Inference shall be refused for a participant without a completed calibration capture | Functional | **Must** | Calibration supplies both the %CAL reference and the OOD check | Thesis §5.12 limitation 1; §6.4 |
| **FR-03** | Calibration shall require ≥20 labelled windows per calibrated task, distributed across ≥3 non-contiguous blocks | Functional | **Must** | Measured supervised-calibration budget | ResNet-SE+CD 81.8 → 85.4% at K = 20; crossover ~50 contiguous vs ~20 spread |
| **FR-04** | Calibration shall be tracked **per task**; uncalibrated tasks are excluded from the output space rather than predicted and filtered | Functional | **Must** | Many rehabilitation participants cannot safely descend stairs | Clinical constraint; ~29 pp per-subject difficulty spread (§5.4) |
| **FR-05** | The system shall refuse segmentation for participants beyond the OOD threshold | Functional | **Must** | Healthy-only cohort; clinical generalisation stated as unknown and critical | §5.12, §5.12.1, §6.4 |
| **FR-06** | Per-window predictions shall be temporally smoothed: 5-window majority vote, then per-class minimum dwell | Functional | **Must** | Named thesis future work, and one of the two mechanisms §5.8.1 conditions its claim on | §5.8.1, §5.13, §2.4.1 |
| **FR-07** | Bouts whose DNS/WAK probabilities fall within a margin, or whose mean confidence is low, shall be surfaced first for review | Functional | **Must** | Measured confusion structure — the model's specific weakness | DNS→WAK confusion 12.5% (single classical models) → **6.6%** (serving ensemble); DNS the ensemble's weakest class at **F1 0.81** |
| **FR-08** | No metric shall be computed or displayed before the operator approves the segmentation | Functional | **Must** | The ethical spine. Without it the tool is an oracle again | Design decision, following from FR-07's premise |
| **FR-09** | Accuracy shall be reported with its measurement regime named | Functional | **Must** | 0.858 is transductive; 0.817 is causal and does not describe this system | §5.11, §6.5 |
| **FR-10** | Model version, artefact hash and calibration version shall be recorded against every inference | Functional | **Must** | The deep model of record changed mid-thesis; results are only comparable when provenance is known | §5.2, §5.8 |
| **NFR-01** | A 10-minute session shall process in ≤30 s | Performance | **Must** | Batch analysis, not a control cycle | — |
| **NFR-02** | The serving ensemble shall exclude Random Forest | Performance | **Should** | RF dilutes the vote *and* dominates latency | SVM + ResNet-SE+CD 0.858 > four-model 0.847; RF 30.5 ms/window |
| **NFR-03** | Normalisation statistics shall never be shared between participants or sessions | Correctness | **Must** | Between-subject shift is a location shift, not noise | Subject-identity probe 0.777 → 0.024 after per-subject normalisation |
| **NFR-04** | No accuracy figure shall appear without its protocol | Integrity | **Should** | Better-aligned does not mean better-classifying | Class silhouette +0.023 vs −0.006 |

> **On FR-01.** An earlier draft had statistics coming from a prior calibration recording. That is
> a regime the thesis never measured and explicitly warns about — §5.12 limitation 8: *"statistics
> estimated on one session need not transfer to the next even for the same individual."* Computing
> them from the assessment session is exactly the 0.858 condition, is legitimate for retrospective
> batch analysis, and removes the exposure. The requirement changed because the evidence did not
> support the earlier version.

### 4.2 Functional requirements by area, with acceptance criteria

MoSCoW priority in the second column. Every **Must** has a testable acceptance criterion.

#### A · Identity and access

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| A1 | Email/password authentication via Firebase Auth | Must | Unauthenticated request to a protected route → 401 |
| A2 | Roles `clinician` / `admin` via custom claims | Must | Clinician requesting an admin route → 403 |
| A3 | Clinicians see only their own participants | Must | Rules test: cross-clinician read denied |
| A4 | Admin lists clinicians and sets roles | Should | Change effective on next token refresh |
| A5 | 30-minute idle timeout | Should | Manual, documented |

*Won't:* password reset, MFA, SSO, self-registration. Accounts are provisioned.

#### B · Participants

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| B1 | Create with pseudonymous code, age band, sex, affected side, notes | Must | **No free-text name field exists in the schema or the UI** |
| B2 | List, view, edit, soft-delete | Must | Soft-delete hides from the list and retains the audit trail |
| B3 | Per-task calibration state | Must | Four badges: calibrated / insufficient / not attempted |
| B4 | Predicted-difficulty band from the OOD distance | Could | Three bands shown; stored alongside the realised correction rate |

B4 tests a question the thesis raised and could not answer — whether subject difficulty is
predictable — as a by-product of ordinary use. The distance is already computed for FR-05, so the
marginal cost is near zero.

*Won't:* clinical history, diagnosis codes, medication, consent uploads, photographs.

#### C · Calibration

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| C1 | Upload a labelled calibration capture per task | Must | Non-conformant (montage mismatch or missing `label` column) → 409, `MONTAGE_REJECTED`, naming every violating field -- the same refusal D3 uses for the same failure class, deliberately, so a clinician sees one behaviour for "this recording doesn't match the montage" everywhere in the product. Accepts CSV and gzipped CSV on the same terms as D2 |
| C2 | Per-task sufficiency: ≥20 windows across ≥3 non-contiguous blocks | Must | Both counts shown per task; both must pass |
| C3 | Persist the per-channel peak calibration envelope as the %CAL reference | Must | One stored vector of nine values |
| C4 | **OOD guard** — Mahalanobis distance against the pooled training distribution; above threshold, refuse | Must | Out-of-range fixture triggers refusal; asserted by test |
| C5 | Recalibration supersedes, never overwrites | Must | Two calibrations → two records, latest active |

*Won't:* live device capture, timed recording wizard, MVC protocol (CON-3).

#### D · Session upload and segmentation

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| D1 | Browser uploads direct to Cloud Storage via V4 signed URL; the API receives an object name | Must | A 100 MB session uploads successfully (CON-1) |
| D2 | Accept CSV and gzipped CSV; hard cap 10 minutes | Must | Longer → a clear rejection, not a crash. Byte ceilings are checked *before* the object is downloaded and again before it is decompressed, so "not a crash" holds for an oversized or highly-compressed object as well as a long one |
| D3 | **Montage validation** server-side once the object lands | Must | Mismatch → 409, every violation named |
| D4 | Pipeline: window → Freq-72 → whole-session z-score → ONNX ensemble | Must | The same input twice → byte-identical output |
| D5 | Output space restricted to calibrated tasks | Must | An uncalibrated task is never predicted |
| D6 | Temporal smoothing: 5-window majority vote, then minimum dwell | Must | Frozen dwell: WAK 1000 ms, UPS 1200 ms, DNS 1200 ms, STDUP 800 ms |
| D7 | Bout construction from smoothed labels | Must | Adjacent same-label windows merge; start, end and mean confidence recorded |
| D8 | Review flags: DNS↔WAK margin < 0.15, or bout confidence < 0.60 | Must | Flagged bouts surface first |

D6 is a **named contribution**, not plumbing, and its effect has been measured rather than
asserted. The thesis evaluates classification at *window* level only; it never asks what those
labels look like once assembled into bouts, because it was not building a review workflow. That
measurement is therefore new evidence this system produces.

**Measured over the three held-out subjects** (`backend/tests/test_smoothing_effect.py`, 597
windows, 22 true bouts, reproducible with `pytest backend/tests/test_smoothing_effect.py -s`):

| | Unsmoothed | With D6 |
|---|---|---|
| Bouts produced (review workload) | 130 | **17** — 86.9% fewer |
| Fragments per true bout | 6.11 | **1.44** |
| True bouts cleanly recovered | 3 of 22 (14%) | **11 of 22 (50%)** |
| Window accuracy | 0.780 | 0.778 — **−0.2 pp** |

D6 therefore buys a 3.7× increase in bouts a reviewer can accept unedited, and removes six
sevenths of the review workload, for two tenths of a percentage point of window accuracy. That
price is stated because the claim is only falsifiable if it is: on one of the three subjects
(Sub10) smoothing cost 11 pp of window accuracy while still improving bout structure, and the
per-subject table records it rather than hiding it inside the pooled figure.

**Bout purity is deliberately not among these metrics.** With one bout per run of equal labels it
reduces arithmetically to window accuracy, so it would restate the thesis's own measurement while
appearing to add something.

*Won't:* streaming inference, batch multi-file upload, gait-cycle or heel-strike detection,
force-plate or video sync, an HMM with a learned transition matrix (it would encode the
laboratory protocol's task ordering, not physiology).

#### E · Review and correction

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| E1 | Timeline: bouts coloured by task, confidence as opacity, flags marked | Must | A 10-minute session renders without lag |
| E2 | Bout list sorted **ascending by confidence** | Must | Least-certain first, and labelled as such on screen |
| E3 | Relabel a bout to any calibrated task | Must | Persists |
| E4 | Split a bout at a window boundary | Should | Two bouts, no window lost |
| E5 | Merge with an adjacent same-label neighbour | Should | One bout, boundaries correct |
| E6 | Exclude a bout as artefact, transition or unobserved | Must | Excluded from metrics, retained in the record |
| E7 | **Approve segmentation** — explicit gate | Must | No metric computed or shown before approval |
| E8 | Every correction audited with before, after and actor | Must | One audit entry per operation, test-verified |

E2 is the mechanism by which a 0.858 macro-F1 becomes a usable workflow. A chronological queue
would spend the clinician's attention uniformly across bouts the model is certain about.

*Won't:* pixel-drag boundaries, undo/redo, bulk multi-select, collaborative review. Corrections
are discrete operations on window indices.

#### F · Metrics and results

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| F1 | Compute the §3.3 metric set on the approved segmentation only | Must | Matches a hand-computed fixture to 1e-6 |
| F2 | Per-task cards, per-channel amplitude bars, both CCIs, bout counts | Must | Every amplitude labelled `%CAL` |
| F3 | **Non-dismissible intended-use banner** | Must | Present on every screen and in the export |
| F4 | Show correction rate and mean confidence per task | Must | Displayed, not behind a toggle |

*Won't:* cross-session trends, normative bands, inter-task statistics, custom metrics.

#### G · Export

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| G1 | PDF containing participant code, session metadata, segmentation summary, metric tables, model version and artefact hash, calibration version, and the intended-use statement | Should | Every field populated |

*Won't:* CSV export, DOCX, email, digital signature, branding.

#### H · Registry and audit

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| H1 | Read-only model card: version, SHA-256, training protocol, **both accuracy regimes labelled**, held-out validation, montage, failure modes, intended use | Should | Reachable from every page footer |
| H2 | Provenance recorded per inference | Must | Query by session returns the full chain |
| H3 | **Audit log, client-immutable** | Must | Rules deny client update and delete; a test proves it |

**H3's wording is load-bearing.** Firestore rules constrain clients; the Cloud Run service uses
the Admin SDK and bypasses them. The log is client-immutable, not immutable. Claiming otherwise
would be one question away from being dismantled. Logged as TD-08 with a repayment plan.

*Won't:* A/B comparison, model upload via the UI, retraining, drift dashboards.

#### I · Cross-cutting

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| I1 | Pydantic validation everywhere, typed error envelope | Must | A malformed payload → 422, never a stack trace. Includes `participant_id`, `object_name` and `content_type`, the three fields that reach Cloud Storage |
| I2 | Firebase ID-token verification on every route | Must | Absent, expired or wrong-audience → 401 |
| I3 | Rate limit per user per hour, on separate buckets for segmentation, session registration and signed-URL minting | Should | Over the limit → 429; exhausting one bucket does not consume another |
| I4 | Structured JSON logging with no participant identifiers | Must | Log inspection test |
| I5 | Responsive 1920 → 768 px | Should | Verified at three breakpoints |
| I6 | WCAG 2.1 AA contrast | Should | Automated check |
| I7 | Global error boundary | Must | A forced 500 → a usable message |

> **On the three refinements above (C1, D2, I1, I3).** Each narrows or completes an already-frozen
> control rather than adding one, which is why none appears in `SCOPE_CHANGE_LOG.md`. D2 already
> promised "a clear rejection, not a crash", but the duration cap is expressed in samples and could
> only be applied after the whole object had been downloaded and parsed — so the promise held for a
> long recording and not for a large one. I3 already bounded "the only genuinely expensive route",
> but the two cheaper routes that reach it were unbounded, so the ceiling could be walked around
> rather than hit. C1's own criterion exists to make calibration and session uploads behave
> identically for the same class of defect, and they did not: one accepted gzip and the other
> reported it as an unparseable montage. In each case the requirement was already the right one and
> the implementation did not yet meet it. No new user-facing capability was added, and nothing was
> de-scoped to pay for any of it.

> **On E3's retrieval routes (15 Aug).** Two endpoints were added to §10 of the plan of record —
> `GET /v1/participants/{pid}/sessions` and `GET /v1/sessions/{sid}` — and, on the same reasoning,
> no `SCOPE_CHANGE_LOG.md` entry was written. **E3's acceptance criterion is the single word
> "Persists."** It did: a relabel was written to Firestore and survived. It was also unobservable
> from anywhere, because no route returned a session or its bouts, so the criterion could not be
> tested by any caller and a clinician who closed the tab lost the correction permanently. The
> frozen surface already carried two GETs keyed by a session id — `.../metrics` and `.../export` —
> and nothing that would ever produce one, which is an internal inconsistency rather than a
> deliberate minimum. `GET /v1/sessions/{sid}` returns the exact response body `POST .../segment`
> already returned, and the list returns records the API was already writing; both are scoped by
> the owning participant, so A3 is enforced exactly where it was. No new capability, no new
> computation, nothing de-scoped to pay for it. Found by using the deployed product as the
> examiner will, which is also where the criterion's untestability first became visible.

### 4.3 Explicitly out of scope

Pre-decided so that a temptation at hour 31 needs no deliberation. Each exclusion carries its
reason, because an exclusion without one is an omission.

| Excluded | Reason |
|---|---|
| Live BLE / streaming inference | No hardware, and the causal normaliser is a measurably different regime (−4.1 pp) |
| Bilateral / symmetry metrics | **Physically impossible** — the montage is unilateral (CON-4) |
| %MVC normalisation | Maximal-effort testing contraindicated in the target populations (CON-3) |
| Cross-session amplitude comparison | Invalid without an MVC anchor; thesis §5.12 item 8 |
| Normative reference bands | No normative database exists for this montage |
| Any clinical-population claim | 40 healthy adults only (CON-6) |
| Retraining or fine-tuning in-app | Minutes of CPU; not a request-cycle activity |
| Model upload via the UI | Arbitrary-artefact execution |
| Multi-tenant isolation | Exceeds the budget, and a fake version is reckless. Logged as TD-03 |
| Gait-cycle detection | Requires an IMU or a force plate |
| Video synchronisation | No data source |
| Phone layout | The timeline is unusable at that width |
| Offline / PWA | Inference is server-side |
| Multi-language | Expensive, and not assessed |
| Email notification | No asynchronous workflow exists |
| Self-registration | Abuse surface |
| Undo / redo | The audit log preserves history |
| Drag bout boundaries | Split, merge and relabel cover the intent |
| HMM transition matrix | Would encode protocol ordering, not physiology |
| Dark mode | Not assessed |
| Fuzzy montage mapping | A silently wrong channel order is the worst available failure |
| Consent or document upload | Contradicts *not a clinical record system* |
| Administrative analytics | Not assessed |
| CSV export | Traded to fund B4 |

### 4.4 The five that are never removed

If the schedule collapses, these survive: **C4** out-of-distribution guard · **D3** montage
validation · **E7** approval gate · **H3** audit log · **F3** intended-use banner.

Everything else is negotiable under the de-scope ladder. These five are what make the system
defensible rather than merely demonstrable, and they are fixed before the ladder is priced
precisely so that a schedule overrun cannot quietly become an ethical one.

---

## 5. Non-functional requirements

| Property | Target | Verified by |
|---|---|---|
| Session processing | ≤30 s for a 10-minute recording | Integration test |
| Upload ceiling | 10-minute session | Rejection test |
| Calibration clinical time | ≤10 minutes for all four tasks | Documented protocol |
| Page load | ≤3 s on 3G Fast | Lighthouse |
| Availability during grading | `min-instances=1` | Manual |
| Determinism | Identical input → byte-identical output | Equivalence test in CI |
| Contrast | WCAG 2.1 AA | Automated check |

**There is deliberately no per-window latency requirement.** The thesis's 125 ms figure is a
*control-cycle* budget for a wearable device, measured single-threaded on a laptop, and §5.12 says
plainly that those figures "establish computational feasibility rather than certify real-time
performance." It belongs on the model card as an inherited property, not in this table.

### 5.1 Security and privacy

- Participants are identified by a pseudonymous code. **No name field exists**, which is a
  stronger guarantee than a policy of not filling one in.
- Age is banded, not dated.
- Logs carry no participant identifier — a pseudonymous code plus a session time is still a
  re-identification surface.
- Firestore rules deny cross-clinician reads and deny all client writes to the audit collection.
- The deployment service-account key never enters the repository; `.gitignore` refuses the
  patterns it would arrive under.

---

## 6. Data and licensing

**SIAT-LLMD** (Wei et al., 2023, *Scientific Data* 10:358, doi:10.1038/s41597-023-02263-3),
released under **CC0 1.0 Universal**, a public-domain dedication. Redistribution is unrestricted
and attribution is not legally required; it is given anyway as a matter of academic practice and
because Examination Rule 6 requires datasets to be acknowledged. 40 healthy adults, ethics
approval **SIAT-IRB-210315-H0555**.

Three subjects — 10, 13 and 22, chosen to span the measured difficulty range — were held out of
the deployment models' training set. They serve three purposes at once: an independent validation
set for the deployed models, realistic demonstration recordings, and an illustration of the
per-subject difficulty spread. Held-out accuracy is reported as **indicative at n = 3, not a
substitute for the n = 40 LOSO figure.**

---

## 7. Verification

Every **Must** requirement has an acceptance criterion in §4.2 and a corresponding entry in the
test log. Verification levels:

| Level | Coverage |
|---|---|
| Unit | Feature extraction against thesis reference vectors; windowing; calibration sufficiency; CCI including the null case; smoothing and dwell |
| Integration | Signed URL → object → features → normalise → infer → smooth → bouts → approve → metrics, through the **real Firestore adapter against a locally-started emulator** — not the in-memory fake the unit suite substitutes. Also pins `firestore.rules` to reality by reading back the collections the application actually writes |
| Model equivalence | ONNX vs native below 1e-4, both models, in the serving runtime |
| Smoothing effect | Bout coherence with and without D6 — a number the thesis does not have. **Measured:** 130 → 17 bouts, 6.11 → 1.44 fragments per true bout, 14% → 50% cleanly recovered, at −0.2 pp window accuracy (§4.2 D) |
| Rules | Cross-clinician denial; unauthenticated denial; audit update and delete denial |
| System | The full journey against the live deployment |
| Security | Authorisation bypass, oversized upload, malformed CSV, injection — log forging, identifiers in logs, document-path injection, report markup, and stored-payload fidelity |
| Performance | Session processing time against the 30 s budget |

---

## 8. Baseline and change control

This specification is baselined at version 1.0. Thereafter:

1. Nothing is added unless its absence makes an already-frozen item **non-functional** — not
   incomplete, non-functional.
2. Any addition is logged in `SCOPE_CHANGE_LOG.md` with a timestamp, the trigger, the cost, **and
   the item de-scoped to pay for it.** Additions are funded, never free.
3. "It would be better if" is not a trigger. It is an entry in the evolution plan.
4. Behind schedule at hour 28, the de-scope ladder executes top-down without renegotiation:
   A4 → G1 → E4/E5 → B4 → H1 → I3. The five in §4.4 carry no rung.

An empty scope-change log is the intended outcome.
