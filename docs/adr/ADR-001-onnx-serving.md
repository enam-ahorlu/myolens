# ADR-001: Serve the models as frozen ONNX graphs behind an interface

**Status** Accepted · **Date** in-window, Phase 2

## Context

The two classifiers are prior work from the author's thesis: a support-vector classifier fitted
with scikit-learn 1.8.0 under Python 3.14, and a channel-dropout ResNet-SE trained in PyTorch.
The serving container has to load them and reproduce their outputs exactly, because the accuracy
figures quoted throughout the documentation were measured on the native models and the whole
argument for the product rests on those numbers being the ones it actually delivers.

## Decision

Export both models to ONNX and serve them through `onnxruntime` behind an abstract `Predictor`
interface. **No scikit-learn and no torch in the container.**

## Alternatives considered

**Pickle the scikit-learn model and load the torch state dict.** Rejected. A joblib pickle is
only loadable by a compatible scikit-learn, so the container would be pinned to a bleeding-edge
training stack it has no other reason to carry. Worse, the failure mode is not a clean import
error: scikit-learn will often load a pickle from a nearby version and give subtly different
results. A model that is quietly wrong is far more dangerous here than one that refuses to load,
because every screen downstream would look completely normal.

**Reimplement inference by hand from the fitted coefficients.** Rejected as more work and more
risk than the export, with no benefit.

**Serve from a separate model service.** Rejected as scope. It buys independent scaling that a
48-hour single-lab deployment does not need, and costs a network hop inside the 30-second budget.

## Consequences

**Good.** The container image is roughly 150 MB rather than 350. Cold starts are faster. There
is exactly one runtime to reason about, so the equivalence test is uniform across both models.
The graph is frozen, so there is no version coupling to drift.

**Bad, and paid.** Export correctness is not free, it was logged as TD-05 and rated the
register's only Critical item. It has been retired: maximum absolute delta 4.346e-07 across 200
windows for both models, 100% argmax agreement, measured in the serving runtime, with the 1e-4
tolerance **not** relaxed. The regression test runs in CI on every commit.

Getting there surfaced a trap worth recording. The first equivalence run failed at 2.097e-04,
which looks exactly like a broken export. It was not: the reference outputs had been generated on
CUDA while ONNX ran on CPU, and the discrepancy was a kernel difference, not an export defect.
Regenerating the references on CPU gave 4.346e-07, a 480-fold improvement. **The instinct when an
equivalence test fails by a small margin is to loosen the tolerance. That instinct was wrong
here, and would have been wrong in a way nothing downstream would have revealed.**

**Also bad.** ONNX artefacts are opaque. A future maintainer cannot inspect the model the way
they could a pickle. Mitigated by the model card and by the manifest recording the training
protocol and artefact hashes.

## The interface, and why it exists separately

`Predictor` has two implementations selected by configuration: the SVM+ResNet soft vote (0.858
macro-F1 LOSO) and SVM alone (0.777). That seam is what makes the fallback on the de-scope ladder
a configuration change rather than a rewrite, and it is where the next model attaches without
anything above it changing.
