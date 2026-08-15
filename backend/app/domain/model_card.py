"""The read-only model card (H1: "Should", reachable from every page footer).

Reads ``manifest.json``, the record ``prepare_deployment_artifacts.py`` writes into the
artefact directory at export time, and reshapes it into what H1 asks for: version, SHA-256,
training protocol, both accuracy regimes labelled, held-out validation, montage, failure modes,
intended use. This module only reads what that script produced -- the same division of
responsibility as ``ood_guard.load_ood_stats`` and ``onnx_predictor`` loading frozen graphs
rather than training them.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


class ManifestUnavailable(RuntimeError):
    """``manifest.json`` is missing from the artefact directory.

    Raised rather than serving a model card with silently absent fields: a card that renders
    with blanks where the training protocol should be looks identical to one that loaded
    correctly, and H1 exists specifically so a reader does not have to take accuracy on faith.
    """


def load_manifest(artefact_dir: Path) -> dict[str, Any]:
    path = artefact_dir / "manifest.json"
    if not path.exists():
        raise ManifestUnavailable(
            f"{path} not found. Run prepare_deployment_artifacts.py (MSc Python Project) and "
            "redeploy."
        )
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def get_manifest(artefact_dir_str: str) -> dict[str, Any]:
    """Process-wide cached load, the same discipline as ``onnx_predictor.get_ensemble`` and
    ``ood_guard.get_ood_stats``. Keyed on the directory string, not a Path, for the same
    cross-version hashing reason as those two."""
    return load_manifest(Path(artefact_dir_str))
