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
    #: DNS is the ensemble's weakest class (F1 0.81) and DNS->WAK its commonest confusion, still
    #: 6.6% of descent windows after channel dropout and ensembling. The 12.5% figure sometimes
    #: quoted for this boundary belongs to the single classical models, not to what is served.
    dns_wak_margin: float = 0.15

    #: Bouts whose mean confidence falls below this are flagged regardless of class.
    low_confidence_threshold: float = 0.60

    #: Minimum labelled windows per task before that task is considered calibrated. The thesis
    #: measured ResNet-SE+CD rising from 0.818 to 0.854 at K=20 spread across the session.
    min_calibration_windows: int = 20
    min_calibration_blocks: int = 3

    #: Mahalanobis distance beyond which segmentation is refused outright.
    ood_threshold: float = 12.0

    #: I3's ceiling on segmentation, the only genuinely expensive route.
    rate_limit_per_hour: int = 30

    #: Registering an uploaded recording is cheap per call but commits the container to a
    #: download and a full parse, so it is bounded too -- more generously than segmentation,
    #: because a clinician legitimately registers several recordings per session of work.
    session_create_rate_limit_per_hour: int = 60

    #: Minting a signed URL costs almost nothing server-side, but each one is a licence to write
    #: an object into the bucket. Unbounded, that is a storage-cost channel that never touches an
    #: expensive route at all.
    upload_sign_rate_limit_per_hour: int = 120

    #: Byte ceiling applied to an uploaded object before it is downloaded, and again to its
    #: decompressed size before it is parsed. Ten minutes of nine channels at 1920 Hz is roughly
    #: 104 MB of plain CSV and D1's acceptance criterion names a 100 MB upload, so the ceiling
    #: sits above both with headroom. Distinct from D2's ten-minute cap, which is a clinical
    #: limit expressed in samples and can only be checked after decoding.
    max_upload_bytes: int = 160 * 1024 * 1024

    session_processing_budget_seconds: int = 30

    #: Comma-separated origins the browser is allowed to call the API from (CORS). The deployed
    #: frontend and Cloud Run API sit on different origins (myolens.web.app vs .run.app), so
    #: without this every browser call -- not just cross-site ones -- is blocked at the preflight
    #: OPTIONS request before it ever reaches a route handler. Local Vite dev ports are included
    #: so `npm run dev` works against a local or deployed API without extra configuration.
    allowed_origins: str = "https://myolens.web.app,http://localhost:5173,http://127.0.0.1:5173"

    onnx_intra_op_threads: int = Field(default=1, ge=1, le=1)
    onnx_inter_op_threads: int = Field(default=1, ge=1, le=1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
