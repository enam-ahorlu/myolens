"""The out-of-distribution guard's training statistics (C4).

``prepare_deployment_artifacts.py`` never computed or persisted these -- see
``compute_ood_stats.py`` (MSc Python Project) and the "ood_guard" section it adds to
``manifest.json``. This module only loads what that script produced; it does not compute
anything itself, the same division of responsibility as ``onnx_predictor.py`` loading frozen
graphs rather than training them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np


class OodStatsUnavailable(RuntimeError):
    """``ood_stats.npz`` is missing from the artefact directory.

    Raised rather than silently skipping the guard: a calibration endpoint that computes
    sufficiency and %CAL but quietly omits the OOD check would look identical to one that ran
    it and found nothing wrong, and C4 is a Must with a named acceptance test.
    """


def load_ood_stats(artefact_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(mean, inverse_covariance)`` for the pooled training Freq-72 distribution."""
    path = artefact_dir / "ood_stats.npz"
    if not path.exists():
        raise OodStatsUnavailable(
            f"{path} not found. Run compute_ood_stats.py (MSc Python Project) and redeploy."
        )
    data = np.load(path)
    return data["mean"], data["inverse_covariance"]


@lru_cache(maxsize=1)
def get_ood_stats(artefact_dir_str: str) -> tuple[np.ndarray, np.ndarray]:
    """Process-wide cached load. Keyed on the directory string (not a Path) because Path
    objects from different call sites that name the same directory are not guaranteed to
    compare/hash identically across every Python version this service might run under."""
    return load_ood_stats(Path(artefact_dir_str))
