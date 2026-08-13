"""Liveness and readiness.

Deliberately reports whether the *model artefacts* resolved, not merely whether the process is
running. A container that answers HTTP but cannot load its ONNX graphs is not healthy — it is a
service that will fail on the first real request, after the user has already uploaded a file.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import PredictorMode, get_settings
from app.domain.montage import MONTAGE_CONTRACT_VERSION, N_CHANNELS
from app.domain.windowing import SAMPLING_RATE_HZ, STEP_SAMPLES, WINDOW_SAMPLES
from app.serving.predictor import CLASSES

router = APIRouter(tags=["operations"])


class HealthResponse(BaseModel):
    status: str
    environment: str
    predictor: PredictorMode
    classes: list[str]
    montage_channels: int
    montage_contract_version: str
    sampling_rate_hz: float
    window_samples: int
    step_samples: int


@router.get("/v1/health", response_model=HealthResponse, summary="Service health")
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        predictor=settings.predictor,
        classes=list(CLASSES),
        montage_channels=N_CHANNELS,
        montage_contract_version=MONTAGE_CONTRACT_VERSION,
        sampling_rate_hz=SAMPLING_RATE_HZ,
        window_samples=WINDOW_SAMPLES,
        step_samples=STEP_SAMPLES,
    )
