"""Concrete, ONNX-backed predictors.

Two members, because the ensemble consumes two different representations of the same window
and the abstract ``Predictor`` in ``predictor.py`` was written around a single feature array:

* :class:`OnnxSvmPredictor` — Freq-72 features, ``(n_windows, 72)``. A straightforward
  ``Predictor`` implementation.
* :class:`OnnxResnetPredictor` — linear envelope windows, ``(n_windows, 9, 480)``. Still
  implements ``Predictor`` (the interface only promises ``predict``/``artefact_hash``; nothing
  enforces what "features" means to a given member), but its input is not a feature vector and
  its graph outputs logits, not probabilities — softmax happens here, not in the graph.

:class:`EnsemblePredictor` is deliberately *not* a ``Predictor`` itself. It needs both a
features array and an envelope array at once, which the one-argument ``predict(features)``
contract cannot express honestly. Bending the ABC to fit would hide that the ensemble is a
different kind of thing — an orchestrator over two predictors — behind an interface that
implies it takes one array like everything else.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort

from app.domain.windowing import WINDOW_SAMPLES
from app.serving.predictor import (
    CLASSES,
    N_CLASSES,
    N_FEATURES,
    Prediction,
    Predictor,
    hash_artefacts,
    soft_vote,
)

N_CHANNELS = 9


def _session(model_path: Path) -> ort.InferenceSession:
    """A single-threaded session. D4 requires byte-identical output for identical input, and a
    threaded reduction order breaks that — see MODEL_CARD.md §7."""
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    return ort.InferenceSession(
        str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
    )


class OnnxSvmPredictor(Predictor):
    """The Freq-72 SVM. ``probability=True`` at training time plus ``zipmap: False`` at export
    means the graph already emits a plain ``(N, 4)`` probability tensor — no softmax needed."""

    version = "svm-freq72-1.0.0"

    def __init__(self, model_path: Path) -> None:
        self._path = model_path
        self._session = _session(model_path)

    def predict(self, features: np.ndarray) -> Prediction:
        self._validate(features)
        _, probabilities = self._session.run(
            None, {"input": features.astype(np.float32, copy=False)}
        )
        return Prediction(
            probabilities=np.asarray(probabilities, dtype=np.float64),
            model_version=self.version,
            model_hash=self.artefact_hash(),
        )

    def artefact_hash(self) -> str:
        return hash_artefacts([self._path])


class OnnxResnetPredictor(Predictor):
    """ResNet-SE+CD over per-channel linear envelope windows. The graph outputs logits
    (``output_names=["logits"]`` at export, see ``prepare_deployment_artifacts.py``) —
    softmax is applied here, matching the manifest's ``"note": "apply softmax in the service"``.
    """

    version = "resnet-se-cd-1.0.0"

    def __init__(self, model_path: Path, weights_path: Path) -> None:
        # onnxruntime resolves the external-weights sidecar by the relative filename recorded
        # inside the graph, which is why weights_path is not passed to InferenceSession
        # directly — it just has to exist next to model_path with the name the graph expects
        # (resnet_se_cd.onnx.data). Recorded as a parameter anyway so a missing sidecar fails
        # loudly at construction (via the artefact_hash it feeds), not on first inference.
        self._path = model_path
        self._weights_path = weights_path
        if not weights_path.exists():
            raise FileNotFoundError(
                f"{model_path.name} needs its external-weights sidecar {weights_path.name}, "
                "which is not present. Shipping the graph without it produces a container that "
                "starts cleanly and fails on first inference (see backend/artifacts/.gitkeep)."
            )
        self._session = _session(model_path)

    def predict(self, envelopes: np.ndarray) -> Prediction:
        self._validate_envelopes(envelopes)
        (logits,) = self._session.run(None, {"input": envelopes.astype(np.float32, copy=False)})
        logits = np.asarray(logits, dtype=np.float64)
        shifted = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        probabilities = exp / exp.sum(axis=1, keepdims=True)
        return Prediction(
            probabilities=probabilities, model_version=self.version, model_hash=self.artefact_hash()
        )

    def artefact_hash(self) -> str:
        return hash_artefacts([self._path, self._weights_path])

    @staticmethod
    def _validate_envelopes(envelopes: np.ndarray) -> None:
        if envelopes.ndim != 3 or envelopes.shape[1:] != (N_CHANNELS, WINDOW_SAMPLES):
            raise ValueError(
                f"expected (n_windows, {N_CHANNELS}, {WINDOW_SAMPLES}) envelope windows, "
                f"got shape {envelopes.shape}"
            )
        if not np.isfinite(envelopes).all():
            raise ValueError("envelope windows contain non-finite values")


class EnsemblePredictor:
    """The de-scope lever's "on" configuration (``MYOLENS_PREDICTOR=ensemble``).

    Unweighted soft vote, exactly as measured: SVM and ResNet-SE+CD together score 0.858
    macro-F1 LOSO, against 0.777 and 0.840 individually. See ``soft_vote``'s docstring for why
    the vote is not weighted.
    """

    version = "ensemble-1.0.0"

    def __init__(self, svm: OnnxSvmPredictor, resnet: OnnxResnetPredictor) -> None:
        self.svm = svm
        self.resnet = resnet

    def predict(self, features: np.ndarray, envelopes: np.ndarray) -> Prediction:
        if features.shape[0] != envelopes.shape[0]:
            raise ValueError(
                f"features and envelopes must describe the same windows: "
                f"{features.shape[0]} != {envelopes.shape[0]}"
            )
        svm_pred = self.svm.predict(features)
        resnet_pred = self.resnet.predict(envelopes)
        combined = soft_vote(svm_pred.probabilities, resnet_pred.probabilities)
        return Prediction(
            probabilities=combined, model_version=self.version, model_hash=self.artefact_hash()
        )

    def artefact_hash(self) -> str:
        return hash_artefacts([self.svm._path, self.resnet._path, self.resnet._weights_path])


def load_svm(artefact_dir: Path) -> OnnxSvmPredictor:
    return OnnxSvmPredictor(artefact_dir / "svm_freq72.onnx")


def load_resnet(artefact_dir: Path) -> OnnxResnetPredictor:
    return OnnxResnetPredictor(
        artefact_dir / "resnet_se_cd.onnx", artefact_dir / "resnet_se_cd.onnx.data"
    )


def load_ensemble(artefact_dir: Path) -> EnsemblePredictor:
    return EnsemblePredictor(load_svm(artefact_dir), load_resnet(artefact_dir))


__all__ = [
    "CLASSES",
    "N_CHANNELS",
    "N_CLASSES",
    "N_FEATURES",
    "EnsemblePredictor",
    "OnnxResnetPredictor",
    "OnnxSvmPredictor",
    "load_ensemble",
    "load_resnet",
    "load_svm",
]
