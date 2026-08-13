"""Runtime configuration.

Everything that varies between local development, CI and Cloud Run lives here and nowhere else.
Determinism settings are applied at import time because they must be in place before ONNX
Runtime builds a session, and a byte-identical-output requirement that depends on import order
is not a requirement at all.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings

# Applied before onnxruntime is imported anywhere. Thread-level non-determinism in reduction
# order is enough to move a probability in the seventh decimal place, which is enough to flip an
# argmax on a genuinely ambiguous window, which is enough to make "same input, same output"
# false. One thread is slower and correct.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")


class PredictorMode(StrEnum):
    """Which serving configuration to use. The de-scope lever."""

    ENSEMBLE = "ensemble"  # SVM + ResNet-SE+CD soft vote. Measured 0.858 macro-F1 LOSO.
    SVM_ONLY = "svm_only"  # SVM alone. Measured 0.777. The fallback, not the default.


class Settings(BaseSettings):
    """Configuration, read from the environment with safe local defaults."""

    model_config = {"env_prefix": "MYOLENS_", "case_sensitive": False}

    environment: str = "development"
    gcp_project_id: str = ""
    gcp_region: str = "europe-west1"
    storage_bucket: str = ""

    predictor: PredictorMode = PredictorMode.ENSEMBLE
    artefact_dir: str = "artifacts"

    #: Bouts whose top-two margin between DNS and WAK falls below this are flagged for review.
    #: DNS is the model's weakest class (65-70% recall) and DNS->WAK its commonest confusion.
    dns_wak_margin: float = 0.15

    #: Bouts whose mean confidence falls below this are flagged regardless of class.
    low_confidence_threshold: float = 0.60

    #: Minimum labelled windows per task before that task is considered calibrated. The thesis
    #: measured ResNet-SE+CD rising from 0.818 to 0.854 at K=20 spread across the session.
    min_calibration_windows: int = 20
    min_calibration_blocks: int = 3

    #: Mahalanobis distance beyond which segmentation is refused outright.
    ood_threshold: float = 12.0

    rate_limit_per_hour: int = 30
    session_processing_budget_seconds: int = 30

    onnx_intra_op_threads: int = Field(default=1, ge=1, le=1)
    onnx_inter_op_threads: int = Field(default=1, ge=1, le=1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
