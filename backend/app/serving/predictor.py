"""The model-serving boundary.

This module is the seam the architecture is built around. Everything upstream of it works in
terms of windows and probabilities; everything downstream of it is ONNX. Two consequences follow,
and both are the point:

* The SVM-only fallback on the de-scope ladder is a configuration change, not a rewrite. If the
  ResNet artefact fails to load or inference exceeds its budget, ``MYOLENS_PREDICTOR=svm_only``
  degrades the system to a measurably worse but fully functional model instead of taking it down.
* The next model attaches here. Replacing the ensemble means implementing ``Predictor`` and
  registering it, and nothing above this line changes.

The class order is frozen and hardcoded. It is the output order of both ONNX graphs, and a
mismatch between it and the graphs would relabel every prediction consistently and silently —
the single worst failure this system could have, because every screen would look normal.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: Frozen class order. Must match the ONNX graphs' output order exactly.
CLASSES: tuple[str, ...] = ("DNS", "STDUP", "UPS", "WAK")

N_CLASSES = len(CLASSES)

#: Number of features in the frozen Freq-72 specification.
N_FEATURES = 72


@dataclass(frozen=True)
class Prediction:
    """Per-window class probabilities, with the provenance that produced them."""

    probabilities: np.ndarray  # (n_windows, N_CLASSES)
    model_version: str
    model_hash: str

    def __post_init__(self) -> None:
        if self.probabilities.ndim != 2 or self.probabilities.shape[1] != N_CLASSES:
            raise ValueError(
                f"expected (n_windows, {N_CLASSES}) probabilities, "
                f"got shape {self.probabilities.shape}"
            )

    @property
    def labels(self) -> np.ndarray:
        """Argmax class index per window."""
        return self.probabilities.argmax(axis=1)

    @property
    def confidence(self) -> np.ndarray:
        """Winning probability per window."""
        return self.probabilities.max(axis=1)


class Predictor(ABC):
    """A source of per-window class probabilities.

    Implementations must be deterministic: the same features must yield byte-identical
    probabilities across runs and across processes. That is a requirement, not an aspiration —
    it is what makes the equivalence test meaningful and what lets a disputed result be
    reproduced months later.
    """

    #: Identifier recorded against every inference, e.g. ``"ensemble-1.0.0"``.
    version: str

    @abstractmethod
    def predict(self, features: np.ndarray) -> Prediction:
        """Map ``(n_windows, N_FEATURES)`` normalised features to class probabilities."""

    @abstractmethod
    def artefact_hash(self) -> str:
        """SHA-256 over the artefacts backing this predictor, for provenance."""

    @staticmethod
    def _validate(features: np.ndarray) -> None:
        if features.ndim != 2 or features.shape[1] != N_FEATURES:
            raise ValueError(
                f"expected (n_windows, {N_FEATURES}) features, got shape {features.shape}"
            )
        if not np.isfinite(features).all():
            raise ValueError("features contain non-finite values; normalisation likely failed")


def hash_artefacts(paths: list[Path]) -> str:
    """Stable SHA-256 over a set of artefact files, order-independent."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def soft_vote(*probability_sets: np.ndarray) -> np.ndarray:
    """Average class probabilities across models.

    Deliberately unweighted. The thesis measured a two-model soft vote of the SVM and the
    channel-dropout ResNet-SE at 0.858 macro-F1, against 0.847 for a four-model vote that
    included Random Forest — adding a weaker model diluted the result *and* dominated latency at
    30.5 ms per window. Weighting the vote would be a new hyperparameter fitted on no held-out
    data, so the serving ensemble is exactly the configuration that was measured.
    """
    if not probability_sets:
        raise ValueError("soft vote requires at least one set of probabilities")
    shapes = {p.shape for p in probability_sets}
    if len(shapes) != 1:
        raise ValueError(f"probability sets disagree on shape: {shapes}")
    stacked = np.stack(probability_sets, axis=0)
    return stacked.mean(axis=0)


# TODO(TD-02): inference is offline-batch only; there is no streaming path.
# Prudent & deliberate. A live path needs a causal normaliser, and the thesis measured that
# regime at 0.817 macro-F1 against 0.858 transductive — a different and worse number that would
# have to be re-reported everywhere. There is also no hardware to stream from.
# Impact: complete recordings only. Priority: Medium.
# Repayment: v2.0, causal ring buffer behind this same interface, with the causal figure quoted
# as the operating number rather than the transductive one.
