# Declaration of prior work, third-party components and tooling

**Enam Ahorlu · CSCD602 Advanced Software Engineering · Individual Project Examination**

This declaration appears on page 2 of `Project_Documentation.pdf` and is reproduced here so that
it is visible in the repository as well as in the submission.

---

## 1. Prior work

The machine-learning model served by this application is a pre-existing research artefact from my
MSc thesis, *Surface Electromyography-Based Lower-Limb Movement Recognition Using Classical
Machine Learning and Deep Learning Approaches*. The feature-extraction specification (Freq-72),
the trained support-vector classifier and the channel-dropout-augmented ResNet-SE network were
developed and evaluated before this examination period, and are disclosed here under Examination
Rule 12.

They are treated as an external dependency, as any third-party library would be. They are loaded
as frozen ONNX graphs, their equivalence to the native models is proved by test, and no training
code forms part of this submission. The demonstration recordings shipped with the application are
built from three subjects held out of that training, and the model card in `docs/MODEL_CARD.md`
records the provenance, the measured accuracy under each protocol, and the known failure modes.

## 2. The application

The software system described in this documentation was designed and built within the 48-hour
examination period, as Examination Rule 3 requires. No application source code predates it. The
repository was created at the start of the window specifically so that the entire commit history
is verifiable as falling inside it.

## 3. Use of AI assistance

An AI assistant (Claude) was used on this project as a development tool.

**Where it was used.** Reviewing my thesis for applicable findings and their limits; interrogating
the project's scope for over-reach; deriving the function point count and the effort arithmetic;
drafting and refactoring application source code; and generating test cases.

**How the work was directed and checked.** Every requirement in this specification traces to a
measurement in my own thesis or to a stated clinical constraint, and I supplied those traces; the
tool did not infer them. The scope freeze, the anti-creep list, the de-scope ordering and the five
never-removed behaviours are my decisions. Numerical results quoted anywhere in this submission
are my own measurements. Where the assistant computed a figure, whether the function point count,
the COCOMO effort or the PERT range, the working is retained in a spreadsheet of live formulas, so
the arithmetic is auditable and not merely asserted. I reviewed, executed and tested all generated
code before commit.

**What it did not do.** It did not select the research problem, produce the experimental results
the application serves, or determine what the system should refuse to do. It was not treated as a

I accept full responsibility for the entire contents of this submission.

## 4. Dataset

The underlying dataset is **SIAT-LLMD** (Wei et al., 2023, *Scientific Data* 10:358,
doi:10.1038/s41597-023-02263-3), released under a **CC0 1.0 Universal** public-domain dedication
and used with attribution as a matter of academic practice. It comprises recordings from 40
healthy adults under ethics approval **SIAT-IRB-210315-H0555**. No data from this application's
users forms part of it.

The dataset's second corpus used in the thesis, ENABL3S, is **not** shipped: at seven channels
and 1 kHz it violates this application's montage contract. That exclusion is deliberate and is
evidence that the contract is enforced rather than declared.

## 5. Third-party components

Firebase Authentication, Cloud Firestore, Cloud Storage, Cloud Run and Firebase Hosting are used
as managed services. ONNX Runtime, FastAPI, Pydantic, NumPy, SciPy, PyWavelets, React, Vite and
Vitest are used under their respective open-source licences.

The interface design was built on the **MediCare Admin Dashboard UI Kit**, a Figma Community
resource by UI Expert (Figma handle `@uiexpert`), used under a **CC BY 4.0** (Creative Commons
Attribution 4.0 International) licence:
https://www.figma.com/community/file/1604474505029333381/medicare-admin-dashboard-ui-kit.
Attribution is recorded here because CC BY 4.0 makes it a licence condition, not a courtesy. The
kit supplied a starting layout and component set only; the palette, type scale, spacing, radii and
all other design tokens actually shipped in this application are this project's own, derived and
verified in `scripts/verify_palette.py` and recorded in `docs/DESIGN_TOKENS.md`, not the kit's.
