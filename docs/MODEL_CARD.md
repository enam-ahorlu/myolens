# Model Card: MyoLens Movement Segmentation Ensemble

**Version** `1.0.0` · **Built** 2026-08-13T04:49:25Z · **Status** verified, not clinically validated

---

## 1. What this is

A two-member soft-vote ensemble that assigns one of four lower-limb movement classes to a 250 ms window of nine-channel surface electromyography. In MyoLens it does **not** produce a clinical finding. It produces a first-pass segmentation of a recording into task bouts, which a clinician reviews and corrects before any metric is computed.

| Member | File | SHA-256 (first 16) | Size |
|---|---|---|---|
| SVM (Freq-72, RBF) | `svm_freq72.onnx` | `c443dc1116db409e` | 3,266 KB |
| ResNet-SE + channel dropout | `resnet_se_cd.onnx` | `17b6ebac207425c9` | 145 KB |
| ResNet external weights | `resnet_se_cd.onnx.data` | | 2,170 KB |

**Both ResNet files must be deployed together.** The `.onnx` holds the graph; the weights live in the sidecar `.data`. Shipping one without the other fails at load time.

**Classes, in fixed order:** `["DNS", "STDUP", "UPS", "WAK"]`, descending stairs, sit-to-stand, ascending stairs, level walking. This order is hard-coded on both sides of the ensemble. It is not derived from the data at runtime, because deriving it is how the two members' probability columns silently stop aligning.

**Combination rule:** unweighted arithmetic mean of the two probability vectors, then `argmax`. No weighting, no calibration layer.

---

## 2. Intended use

**In scope.** Research and clinical-education analysis of multi-task sEMG recordings from able-bodied and mildly-impaired ambulatory adults, using the montage in §4, where a human reviews and approves the segmentation before it is used.

**Out of scope, explicitly.**

- **Not a medical device.** Not for diagnosis, treatment, or clinical decision-making.
- **Not validated on any clinical population.** Trained and evaluated entirely on healthy adults. Performance on hemiparetic, post-arthroplasty, amputee or cerebral-palsy gait is unknown, and the failure would be silent, because a softmax returns high confidence on inputs unlike anything it has seen. MyoLens guards this with a Mahalanobis out-of-distribution check that refuses rather than guesses.
- **Not a controller.** The model originates in a prosthetic-control thesis, where a descending-stairs-read-as-walking error is a fall risk. MyoLens has no controller and no fall. That confusion is tracked here as a *review-priority* signal, not a safety claim.
- **Not for any other montage.** See §4.

---

## 3. Training data

**SIAT-LLMD**. Wei, W., Tan, F., Zhang, H., Mao, H., Fu, M., Samuel, O. W., & Li, G. (2023). Surface electromyogram, kinematic, and kinetic dataset of lower limb walking for movement intent recognition. *Scientific Data*, 10, 358. https://doi.org/10.1038/s41597-023-02263-3

- 40 healthy adults, ethics approval **SIAT-IRB-210315-H0555**
- Licence **CC0 1.0 Universal**, a public-domain dedication. Redistribution is unrestricted and attribution is not legally required; it is given here as a matter of academic practice and to satisfy examination Rule 6.
- 26,347 windows across the four classes: STDUP 14,686 (55.7%), UPS 4,550, DNS 4,069, WAK 3,042

**Split.** Trained on **37 subjects**. Subjects **10, 13 and 22** were held out entirely and never contributed to training, validation or model selection. The thesis identifies one of the three as among the hardest, one among the easiest and one middling. Within the 37, six subjects (5, 16, 20, 29, 33, 39) formed the deep model's early-stopping validation set.

---

## 4. Input contract

**The model will produce confident nonsense on a non-conforming montage.** MyoLens rejects such uploads at the API rather than attempting to map them.

| # | Channel (exact string) | Group |
|---|---|---|
| 1 | `sEMG: tensor fascia lata` | hip abductor |
| 2 | `sEMG: rectus femoris` | knee extensor |
| 3 | `sEMG: vastus medialis` | knee extensor |
| 4 | `sEMG: semimembranosus` | knee flexor |
| 5 | `sEMG: upper tibialis anterior` | dorsiflexor |
| 6 | `sEMG: lower tibialis anterior` | dorsiflexor |
| 7 | `sEMG: lateral gastrocnemius` | plantarflexor |
| 8 | `sEMG: medial gastrocnemius` | plantarflexor |
| 9 | `sEMG: soleus` | plantarflexor |

**Unilateral, one leg.** No bilateral or symmetry metric is derivable from this montage, and none is offered.

**Signal chain:** sample rate **1920 Hz** · band-pass 20–450 Hz, 4th order · linear envelope 50 ms · window **480 samples (250 ms)** · step **240 samples (125 ms)**.

> **On the sampling rate.** The recordings are 1920 Hz, `meta["fs"] = 1920.0001344`, and 480 ÷ 1920 = 0.250 s exactly. The originating thesis states 2000 Hz; that figure is incorrect, though the 250 ms window it describes is right. Separately, the feature extractor **hard-codes 2000.0** when computing mean and median frequency, so those two feature families carry a constant scale factor of 2000/1920 ≈ 1.042. Per-column z-scoring absorbs a constant scale exactly, so no classification result is affected, but **the serving feature extractor must keep the 2000.0 constant**, because reproducing the model matters more than being right about hertz. Any MNF or MDF quoted in absolute Hz elsewhere is ~4% high.

**Feature vector (SVM), 72 dimensions, feature-major**, eight blocks of nine channels, in this order:

`MAV · RMS · WL · ZC · WAMP · MNF · MDF · log1p(spectral power)`

Zero-crossing and Willison-amplitude thresholds both 1e-6. Spectrum via `rfft`, no window function, no detrend, no zero-padding.

---

## 5. Normalisation: read this before deploying

**Both graphs expect input that has already been normalised. Neither performs normalisation internally, and no normalisation statistics ship with them.**

The thesis's per-subject z-score is *transductive*: every subject, including held-out ones, is standardised by that subject's own statistics. There is consequently nothing to fit and persist. A wearable device would have to accumulate the wearer's own windows and estimate statistics online, the causal problem that costs about 4 percentage points.

MyoLens does not have that problem, because it analyses a complete uploaded recording. The service computes statistics **from the assessment session itself, over the whole recording**, which is exactly the condition under which the headline figures were measured.

- **SVM path:** per feature column, over the session's windows. Population standard deviation (ddof = 0), `sd < 1e-8 → 1.0`.
- **ResNet path:** per channel, pooled over the session's windows *and* time (axes 0 and 2). Same ddof and guard.

Statistics are never shared between participants or between sessions.

---

## 6. Performance

Two different things get called "accuracy" here, and conflating them is the most likely way to mislead a reader.

### Held-out subjects (this artefact)

Subjects 10, 13, 22 · n = 1,983 windows · computed on CPU, the serving device.

| Model | Macro-F1 | Balanced accuracy |
|---|---|---|
| SVM Freq-72 | 0.7907 | 0.7894 |
| ResNet-SE+CD | 0.8679 | 0.8729 |
| **Soft-vote ensemble** | **0.8760** | **0.8763** |

**n = 3 subjects. This is indicative, not a substitute for the LOSO figure below.** With a ~29 percentage-point spread in per-subject difficulty, three subjects cannot characterise the distribution. All three figures land 1.3–2.8 pp above their LOSO counterparts, which is consistent with small-sample variation and should not be read as the deployment model being better.

### Leave-one-subject-out (the thesis, n = 40)

| Configuration | Macro-F1 |
|---|---|
| SVM Freq-72, per-subject norm | 0.777 |
| ResNet-SE+CD | 0.840 |
| **Soft-vote ensemble, transductive** | **0.858** |
| Soft-vote ensemble, causal 100-window buffer | 0.817 |

**0.858 is the figure MyoLens reports**, because whole-session transductive normalisation is the regime MyoLens actually runs in. **0.817 is the figure a real-time wearable would see**, and it is quoted alongside so no reader assumes the number transfers to a device. Reporting the causal figure here would understate the system, which is no more honest than overstating it.

### Known failure modes

- **Descending stairs is the weakest class throughout**, roughly 0.64–0.68 F1 for single models, rising to about 0.81 in the ensemble, and still last of the four. Its dominant confusion is with level walking.
- **Subject difficulty is a property of the data, not the model**, the same subjects are hard for every model tried (cross-model correlation r = 0.74–0.83). MyoLens surfaces a predicted-difficulty band from the OOD distance for this reason.
- **Per-window classification alone produces physiologically impossible transitions.** MyoLens applies a 5-window majority vote and per-class minimum dwell before constructing bouts. This layer is not part of the model.
- **Sit-to-stand is 55.7% of training windows.** Its high score is not imbalance inflation, precision and recall are both high and closely matched, and downsampling it by 74% moved its F1 by under 1.2 pp.

---

## 7. Verification

Technical-debt item **TD-05, paid**. Run in a Python 3.12 environment with `onnxruntime 1.28.0`, matching the serving container rather than the environment that produced the artefacts.

| Check | Result |
|---|---|
| SVM, ONNX vs native | max abs Δ **2.594e-05** |
| ResNet, ONNX vs native | max abs Δ **4.346e-07** |
| Soft vote, end to end | max abs Δ **1.297e-05** |
| Argmax agreement | **100%** on all three |
| Repeat run byte-identical | yes |

Tolerance 1e-4. An initial run failed at 2.097e-04 because the reference came from CUDA while ONNX ran on CPU; holding the device constant reduced the difference by a factor of 480, confirming the deviation was kernel difference and not export error. The tolerance was not relaxed.

**Determinism requires pinning.** The service sets `intra_op_num_threads = 1`, `inter_op_num_threads = 1`, `OMP_NUM_THREADS = 1`. Without these, ONNX Runtime's thread scheduling makes repeat runs non-identical.

---

## 8. Reproducibility

Seed 42 throughout. `cudnn.deterministic = True`, `cudnn.benchmark = False`, without them, two runs at the same seed differed by roughly half a point.

**SVM.** `SVC(kernel="rbf", C=1.0, gamma="scale", class_weight="balanced", probability=True, cache_size=500, random_state=42)`. No scaler in the pipeline; input arrives pre-normalised.

**ResNet-SE+CD.** `EMGResNet1D`, squeeze-and-excitation enabled, **557,276 parameters**. Adam, lr 1e-3, weight decay 1e-4, `CosineAnnealingLR(T_max=40)`, cross-entropy with balanced class weights, batch 512, up to 40 epochs, early stopping patience 7 on validation loss.

**Channel dropout, p = 0.2**, applied to training batches only, per sample and per channel, broadcast across all 480 timesteps. **There is deliberately no `1/(1-p)` rescaling**, surviving channels are not scaled up, so training-time input energy sits about 20% below inference-time. This looks like a defect and is not: it is the configuration under which the thesis's 84.0% was obtained, and changing it would invalidate the comparison.

Regeneration: `python prepare_deployment_artifacts.py --root . --out <dir>` in the thesis environment, then `verify_onnx_equivalence.py --artifacts <dir>` in the 3.12 environment.

---

## 9. Provenance and disclosure

These artefacts derive from my MSc thesis, *Surface Electromyography-Based Lower-Limb Movement Recognition Using Classical Machine Learning and Deep Learning Approaches*, a **prosthetic-control** thesis. The feature specification and both model architectures predate the CSCD602 examination period and are disclosed under Rule 12. They are treated as an external dependency.

MyoLens's non-control application is the one the thesis itself carves out in §5.8.1: *"for less safety-critical applications, such as gait-phase monitoring, activity logging, or rehabilitation progress tracking, a macro F1 of around 80% across four classes may well be enough, especially once temporal smoothing or confidence thresholds are added to reject low-certainty predictions."* MyoLens implements both named mechanisms.

**Citation:** Wei et al. (2023), *Scientific Data* 10:358, doi:10.1038/s41597-023-02263-3. CC0 1.0 Universal.
