# ADR-003 — Normalise per session, transductively, over the whole recording

**Status** Accepted · **Date** in-window, Phase 2 · **Supersedes** an earlier draft requirement

## Context

Between-subject variation in sEMG is a location shift, not noise. The thesis measured it directly:
a probe trained to predict subject identity from raw features scored 0.777, and after per-subject
normalisation the same probe scored **0.024**. Normalisation is not a preprocessing detail here;
it is the single largest lever on accuracy in the whole system — worth +6.9 percentage points of
macro-F1 on the SVM (70.8 → 77.7, p < 0.0001, d = 1.48), replicated at +10.3 pp on a second
corpus.

The question is *which* data the statistics are computed from.

## Decision

Compute normalisation statistics **from the assessment session itself, over the whole recording**,
before inference. This is the transductive regime, and it is exactly the condition under which
the reported 0.858 macro-F1 was measured.

## Alternatives considered

**Statistics from the participant's prior calibration recording.** This was the earlier draft
requirement, and it was wrong. The thesis never measured that regime, and §5.12 limitation 8 warns
against assuming it: *"statistics estimated on one session need not transfer to the next even for
the same individual."* Shipping it would have meant quoting an accuracy figure obtained under one
condition while operating under a different, unmeasured one. **The requirement changed because the
evidence did not support it** — recorded here rather than quietly corrected, because the change is
more informative than the result.

**Causal statistics from a trailing buffer.** Measured, and it costs real accuracy: 0.817 against
0.858, a 4.1 pp drop. It is the honest choice for a live wearable, where future samples do not
exist. MyoLens analyses complete uploaded recordings, so the future *does* exist, and refusing to
use it would throw away accuracy for no benefit.

**Global statistics across all participants.** Rejected outright; it is the condition the 0.024
probe result says to avoid.

## Consequences

**Good.** The deployed system operates in the regime its headline number was measured in. That is
the whole point, and it is what lets FR-09 report 0.858 without a caveat about regime mismatch.

**Bad, and it constrains the roadmap.** Transductive normalisation requires the whole recording up
front, which makes streaming inference impossible without changing the regime. That is TD-02, and
the repayment plan explicitly says a live version must quote 0.817 rather than 0.858 — because it
would be a different system, measured differently.

**Correctness constraint.** Statistics must never be shared between participants or between
sessions (NFR-03). Sharing them would reintroduce exactly the between-subject shift the
normalisation exists to remove, and would do so silently.

**Reporting constraint.** Both figures appear together everywhere, with their regimes named. 0.858
transductive is what this system does; 0.817 causal is what a wearable would do. Quoting either
alone would be a claim the measurement does not support.
