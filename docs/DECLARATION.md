# Declaration of prior work, third-party components and tooling

**Enam Ahorlu · CSCD602 Advanced Software Engineering · Individual Project Examination**

This declaration appears on page 2 of `Project_Documentation.pdf` and is reproduced here so that
it is visible in the repository as well as in the submission.

---

## 1. Prior work

The machine-learning model served by this application is a pre-existing research artefact from
the author's MSc thesis, *Surface Electromyography-Based Lower-Limb Movement Recognition Using
Classical Machine Learning and Deep Learning Approaches*. The feature-extraction specification
(Freq-72), the trained support-vector classifier and the channel-dropout-augmented ResNet-SE
network were developed and evaluated **before** this examination period and are disclosed here
under Examination Rule 12. They are treated as an external dependency, as any third-party library
would be: they are loaded as frozen ONNX graphs, their equivalence to the native models is proved
by test, and no training code forms part of this submission.

## 2. Work prepared before the examination window

Three artefacts were prepared before the clock started. None of them is submitted as a marked
deliverable in the form in which it was prepared; each was re-authored inside the window against
the requirements as they actually settled.

| Artefact | What it is | Status |
|---|---|---|
| Deployment models and demo data | ONNX exports of the two thesis models, an equivalence-test fixture, a model card, and demonstration recordings built from three held-out subjects | Pre-clock. Disclosed as prior work under §1. |
| Interface design | Ten screens and a design-token system in Figma, and four structural diagrams in FigJam — deployment, sequence, data model, internal component layering | Pre-clock, deliberately. Design preceded implementation rather than following it. |
| Effort-estimation workbook | Function point count, COCOMO 81 organic calculation and PERT work breakdown, as a spreadsheet of live formulas | Pre-clock as arithmetic. The estimation **section** of the report was written inside the window against the completed SRS. |

The interface design was completed before implementation as a deliberate methodological choice,
in contrast to an earlier group project on which screens were drawn after the code existed — with
the result that the design artefact described the software rather than specifying it.

## 3. Work performed inside the examination window

The software system described in this documentation — its requirements specification, effort
estimation write-up, architecture, implementation, test suite, deployment configuration and
documentation — was designed and built entirely within the 48-hour examination period. **No
application source code predates it.** The repository was created at the start of the window
specifically so that the entire commit history is verifiable as falling inside it.

## 4. Use of AI assistance

An AI assistant (Claude) was used throughout this project as a development and drafting tool. Its
use is disclosed here in full rather than characterised generally.

**Where it was used.** Reviewing the thesis for applicable findings and their limits; interrogating
the project's scope for over-reach; producing the Figma screens and FigJam diagrams from written
specifications; deriving the function point count and effort arithmetic; drafting and refactoring
application source code; drafting documentation; and generating test cases.

**How the work was directed and checked.** Every requirement in this specification traces to a
measurement in the author's own thesis or to a stated clinical constraint, and those traces were
supplied by the author, not inferred by the tool. The scope freeze, the anti-creep list, the
de-scope ordering and the five never-removed behaviours are the author's decisions. Numerical
results quoted anywhere in this submission are the author's own measurements; where the assistant
computed a figure — the function point count, the COCOMO effort, the PERT range — the working is
retained in a spreadsheet of live formulas so the arithmetic is auditable rather than asserted.
All generated code was reviewed, executed and tested by the author before commit.

**What it did not do.** It did not select the research problem, produce the experimental results
the application serves, or determine what the system should refuse to do. It was not treated as
a source: no claim in this submission rests on the assistant's assertion of a fact.

The author accepts full responsibility for the entire contents of this submission.

## 5. Dataset

The underlying dataset is **SIAT-LLMD** (Wei et al., 2023, *Scientific Data* 10:358,
doi:10.1038/s41597-023-02263-3), released under a **CC0 1.0 Universal** public-domain dedication
and used with attribution as a matter of academic practice. It comprises recordings from 40
healthy adults under ethics approval **SIAT-IRB-210315-H0555**. No data from this application's
users forms part of it.

The dataset's second corpus used in the thesis, ENABL3S, is **not** shipped: at seven channels
and 1 kHz it violates this application's montage contract. That exclusion is deliberate and is
evidence that the contract is enforced rather than declared.

## 6. Third-party components

Firebase Authentication, Cloud Firestore, Cloud Storage, Cloud Run and Firebase Hosting are used
as managed services. ONNX Runtime, FastAPI, Pydantic, NumPy, SciPy, PyWavelets, React, Vite and
Vitest are used under their respective open-source licences.
