# MyoLens

**Task-conditioned sEMG session analysis with reviewable automatic segmentation.**

MyoLens segments a multi-task lower-limb surface-EMG recording into movement bouts, has a
clinician review and correct that segmentation, and **only then** computes task-conditioned
muscle activation and co-activation metrics.

The classifier is infrastructure. The metrics are the product. The human is in the loop by design.

---

## Intended use

> MyoLens is a research and clinical-education tool for analysing multi-task surface
> electromyography recordings. It proposes a segmentation of a recording into movement tasks,
> which the operator reviews and corrects, and then reports task-conditioned muscle activation
> and co-activation metrics computed on the approved segmentation.
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

## Why the human is in the loop

The serving ensemble reaches a macro-F1 of **0.858** (leave-one-subject-out, n = 40,
transductive normalisation). That is good enough to propose a segmentation and wrong often
enough that no metric should be computed from it unreviewed. Five behaviours enforce that and
are **never** removed:

| | Guarantee |
|---|---|
| C4 | Out-of-distribution guard — segmentation is refused beyond a Mahalanobis threshold |
| D3 | Montage validation — a non-conforming upload is rejected, never coerced |
| E7 | Approval gate — no metric is computed or displayed before a human approves |
| H3 | Audit log — every correction is recorded with the model's confidence at the time |
| F3 | Intended-use banner — present on every screen and in every export |

## Architecture

React 19 + Vite + TypeScript on Firebase Hosting · FastAPI on Cloud Run · Cloud Firestore ·
Cloud Storage (uploads via V4 signed URL) · ONNX Runtime for inference · GitHub Actions for CI/CD.

Layered, with an explicit model-serving boundary:

```
React -> FastAPI routers -> domain services -> adapters (Firestore, Storage, model runtime)
```

The runtime sits behind `Predictor`, with two implementations selected by configuration. That
seam is why the SVM-only fallback is a config change rather than a rewrite.

## Repository layout

```
backend/     FastAPI service, domain logic, ONNX serving boundary, pytest suite
frontend/    React 19 + Vite + TypeScript client
docs/        Declaration, technical-debt register, scope-change log, ADRs
scripts/     CI gates, including the SATD <-> register consistency check
.github/     Actions workflows
```

## Operating a deployment

There is no self-registration (an abuse surface, on the `Won't` list), so the first account has
to come from outside the application, and an examiner handed a login to an empty system has been
given a credential rather than a demonstration. Two scripts cover both:

```bash
# Provision an account and set its role claim. Needs Application Default Credentials
# (gcloud auth application-default login) -- never a service-account key file.
python scripts/bootstrap_accounts.py --project myolens --email you@example.com --role admin

# Register the three held-out subjects, calibrate, upload, segment, and approve one session.
export MYOLENS_SEED_PASSWORD=...
python scripts/seed_demo_data.py --api-url "$API" --api-key "$WEB_API_KEY" --email demo@example.com
```

The seed script drives the deployed API over the network rather than writing to Firestore
directly, and prints a timed, step-by-step transcript. That makes it the system-test record as
well as the seeding tool: writing documents with the Admin SDK would be faster and would skip
precisely the boundaries worth exercising -- authentication, ownership, montage validation, the
out-of-distribution guard and the approval gate.

## The technical-debt gate

Every debt item is tagged in source as `TODO(TD-nn)` and listed in `docs/TECHNICAL_DEBT.md`.
**CI fails if an ID appears in one and not the other**, in either direction. The register is
enforced by the build, not written at the end.

```bash
python scripts/check_satd.py
```

## Local development

```bash
# Backend
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload

# Front end
cd frontend
npm install
npm run dev
```

## Data

SIAT-LLMD (Wei et al., 2023, *Scientific Data* 10:358, doi:10.1038/s41597-023-02263-3),
released under CC0 1.0 Universal. 40 healthy adults, ethics approval SIAT-IRB-210315-H0555.
No data from this application's users forms part of it.

## Declaration

See [`docs/DECLARATION.md`](docs/DECLARATION.md) for the disclosure of prior work, third-party
components, and tooling.
