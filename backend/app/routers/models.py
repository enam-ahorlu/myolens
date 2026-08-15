"""The model card (H1: "Should", reachable from every page footer).

Read-only and unauthenticated -- deliberately, and for the same reason as ``/v1/health``: it
carries no participant data, and a card that could not be checked without first signing in would
defeat the point of publishing provenance. It answers exactly what H1 asks for: version,
SHA-256, training protocol, both accuracy regimes labelled, held-out validation, montage,
failure modes, intended use.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import PredictorMode, get_settings
from app.domain.model_card import get_manifest
from app.domain.montage import MONTAGE, MONTAGE_CONTRACT_VERSION
from app.serving.onnx_predictor import CLASSES, get_ensemble

router = APIRouter(tags=["operations"])

#: Frozen thesis results, not derivable from the manifest, which records only held-out figures.
#: 0.858 is the soft-vote ensemble under transductive per-subject normalisation, LOSO over 40
#: subjects -- the configuration this service serves. 0.817 is the same models under causal
#: normalisation and describes a system MyoLens is not.
LOSO_TRANSDUCTIVE_MACRO_F1 = 0.858
LOSO_CAUSAL_MACRO_F1 = 0.817

#: The public statement, verbatim from SRS §2.2 -- "This statement ships in the product, on
#: every screen and in every export." The model card is one more place it ships.
INTENDED_USE_STATEMENT = (
    "MyoLens is a research and clinical-education tool for analysing multi-task surface "
    "electromyography recordings. It proposes a segmentation of a recording into movement "
    "tasks, which the operator reviews and corrects, and then reports task-conditioned muscle "
    "activation and co-activation metrics computed on the approved segmentation.\n\n"
    "MyoLens is not a medical device and is not intended for diagnosis, treatment, or clinical "
    "decision-making. Its classification model was developed on recordings from 40 healthy "
    "adults (SIAT-LLMD; Wei et al., 2023) and has not been validated on any clinical "
    "population. It is intended for able-bodied and mildly-impaired ambulatory adults, using "
    "the specified nine-channel unilateral lower-limb montage only.\n\n"
    "Amplitude metrics are normalised to the participant's own within-session calibration "
    "reference (%CAL) and are not maximum-voluntary-contraction normalised. Amplitude values "
    "are not comparable across sessions."
)


class AccuracyRegime(BaseModel):
    """A held-out figure for one predictor configuration. Indicative at n = 3 (SRS §6)."""

    predictor: PredictorMode
    label: str
    macro_f1: float
    balanced_acc: float
    n_windows: int


class LosoRegime(BaseModel):
    """A leave-one-subject-out figure, with the normalisation regime that produced it.

    This is what FR-09 means by "accuracy reported with its measurement regime named", and what
    H1 means by "both accuracy regimes labelled". The card previously carried only the held-out
    numbers, which are measured on three subjects and run *higher* than the LOSO figures -- so a
    reader saw 0.876 beside "the default" and had no way to reach the defensible 0.858 at n = 40.
    Reporting the optimistic number alone, without the protocol that makes it optimistic, is the
    exact failure NFR-04 exists to prevent.
    """

    regime: str
    label: str
    macro_f1: float
    n_subjects: int
    describes_this_system: bool


class HeldOutValidation(BaseModel):
    holdout_subjects: list[int]
    training_subjects_n: int
    n_windows: int
    seed: int


class TrainingProtocol(BaseModel):
    created_utc: str
    window_ms: int
    step_ms: int
    bandpass_hz: list[int]
    bandpass_order: int
    envelope_ms: int
    normalisation_mode: str


class ModelCardResponse(BaseModel):
    active_predictor: PredictorMode
    active_version: str
    active_sha256: str
    #: The headline figures, at n = 40. Listed first because they are the defensible ones.
    loso_accuracy: list[LosoRegime]
    accuracy_regimes: list[AccuracyRegime]
    held_out_validation: HeldOutValidation
    training_protocol: TrainingProtocol
    classes: list[str]
    montage_channels: list[str]
    montage_contract_version: str
    failure_modes: list[str]
    intended_use: str


def _failure_modes(manifest: dict, settings) -> list[str]:
    ood = manifest.get("ood_guard", {})
    p95 = ood.get("training_pool_self_distance", {}).get("p95")
    return [
        "Stair descent (DNS) is the weakest of the four classes for this ensemble, at about 0.81 "
        "F1, and DNS-WAK is its commonest confusion: 6.6% of descent windows are still read as "
        "level walking. (The 0.64-0.68 F1 and 12.5% confusion figures sometimes quoted for this "
        "boundary describe the single classical models, not the ensemble served here.) Bouts near "
        "that boundary are flagged for review rather than trusted outright.",
        f"Bouts whose DNS/WAK probability margin falls below {settings.dns_wak_margin} are "
        "surfaced first for review, before any metric is computed on them.",
        f"Bouts whose mean confidence falls below {settings.low_confidence_threshold} are "
        "flagged for review regardless of predicted class.",
        "Segmentation is refused outright beyond the Mahalanobis out-of-distribution threshold "
        f"({settings.ood_threshold})"
        + (
            f", roughly the 95th percentile of the training pool's own self-distance ({p95:.1f})"
            if p95
            else ""
        )
        + " -- a recording unlike anything the model trained on is rejected, not guessed at.",
        "The model was developed on 40 healthy adults (SIAT-LLMD) under a single montage and "
        "has not been validated on any clinical or impaired-gait population; reported accuracy "
        "does not describe performance outside that cohort.",
        "Inference is offline-batch only: normalisation statistics are computed over the whole "
        "recording, so there is no live/streaming prediction path (see TD-02).",
    ]


@router.get("/v1/models/current", response_model=ModelCardResponse, summary="Current model card")
def current_model_card() -> ModelCardResponse:
    settings = get_settings()
    artefact_dir = Path(settings.artefact_dir).resolve()
    manifest = get_manifest(str(artefact_dir))
    ensemble = get_ensemble(str(artefact_dir))

    svm_holdout = manifest["models"]["svm"]["holdout"]
    ensemble_holdout = manifest["ensemble"]["holdout"]
    window = manifest["window"]
    preprocessing = manifest["preprocessing"]

    if settings.predictor == PredictorMode.SVM_ONLY:
        active_version, active_sha256 = ensemble.svm.version, ensemble.svm.artefact_hash()
    else:
        active_version, active_sha256 = ensemble.version, ensemble.artefact_hash()

    return ModelCardResponse(
        active_predictor=settings.predictor,
        active_version=active_version,
        active_sha256=active_sha256,
        loso_accuracy=[
            LosoRegime(
                regime="transductive",
                label=(
                    "Leave-one-subject-out over 40 subjects, normalisation statistics computed "
                    "over the whole recording being analysed. This is the regime MyoLens runs "
                    "in (FR-01), and this is the figure that describes it."
                ),
                macro_f1=LOSO_TRANSDUCTIVE_MACRO_F1,
                n_subjects=40,
                describes_this_system=True,
            ),
            LosoRegime(
                regime="causal",
                label=(
                    "The same models with statistics estimated from past samples only, as a "
                    "real-time system would have to. Reported so the transductive figure cannot "
                    "be mistaken for a streaming one; MyoLens does not run in this regime "
                    "(TD-02)."
                ),
                macro_f1=LOSO_CAUSAL_MACRO_F1,
                n_subjects=40,
                describes_this_system=False,
            ),
        ],
        accuracy_regimes=[
            AccuracyRegime(
                predictor=PredictorMode.SVM_ONLY,
                label=(
                    "SVM only (Freq-72) -- the fallback, not the default. Held out, n = 3 "
                    "subjects: indicative, not a substitute for the LOSO figure above."
                ),
                macro_f1=svm_holdout["macro_f1"],
                balanced_acc=svm_holdout["balanced_acc"],
                n_windows=svm_holdout["n_windows"],
            ),
            AccuracyRegime(
                predictor=PredictorMode.ENSEMBLE,
                label=(
                    "SVM + ResNet-SE+CD soft-vote ensemble -- the default. Held out, n = 3 "
                    "subjects: indicative, and higher than the n = 40 LOSO figure above, which "
                    "is the one to quote."
                ),
                macro_f1=ensemble_holdout["macro_f1"],
                balanced_acc=ensemble_holdout["balanced_acc"],
                n_windows=ensemble_holdout["n_windows"],
            ),
        ],
        held_out_validation=HeldOutValidation(
            holdout_subjects=manifest["holdout_subjects"],
            training_subjects_n=len(manifest["training_subjects"]),
            n_windows=ensemble_holdout["n_windows"],
            seed=manifest["seed"],
        ),
        training_protocol=TrainingProtocol(
            created_utc=manifest["created_utc"],
            window_ms=window["ms"],
            step_ms=window["step_ms"],
            bandpass_hz=preprocessing["bandpass_hz"],
            bandpass_order=preprocessing["bandpass_order"],
            envelope_ms=preprocessing["envelope_ms"],
            normalisation_mode=manifest["normalisation"]["mode"],
        ),
        classes=list(CLASSES),
        montage_channels=list(MONTAGE),
        montage_contract_version=MONTAGE_CONTRACT_VERSION,
        failure_modes=_failure_modes(manifest, settings),
        intended_use=INTENDED_USE_STATEMENT,
    )
