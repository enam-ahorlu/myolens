"""D6's effect on bout coherence, measured against the unsmoothed baseline (SRS §4.2 D6, §7).

**This is the one number in this system the thesis does not have.** The thesis evaluates
classification at *window* level: macro-F1, per-class F1, confusion rates. It never asks what the
window labels look like once they are assembled into bouts, because it was never building a
review workflow. MyoLens is, and for a reviewer the bout is the unit of work -- so the question
that matters here is not "how many windows are right" but "how many coherent bouts does the
reviewer get handed, and do they correspond to what actually happened".

Run it, with the table printed:

    pytest backend/tests/test_smoothing_effect.py -s

The measurement runs the real pipeline in ``routers/sessions.py::segment_session`` twice over
each held-out subject's recording -- once taking ``argmax`` straight to ``build_bouts``, once
through D6's majority vote and minimum dwell first -- and compares the two segmentations against
the bout-level ground truth in ``artifacts/demo/demo_*_truth.csv``.

Three structural metrics, none of which is window accuracy in disguise:

``bouts produced``
    Raw review workload. Every bout is something a human has to look at.

``fragments per true bout``
    How many separate predicted bouts overlap each true bout. 1.0 is perfect. Higher means the
    reviewer sees one real movement chopped into pieces.

``cleanly recovered``
    True bouts matched by *exactly one* predicted bout that covers at least half of it and
    carries the right label. The strictest of the three, and the one that corresponds to "the
    reviewer can accept this bout without editing it".

Window-level purity is deliberately **not** among them. With one bout per run of equal labels it
reduces arithmetically to window accuracy, so it would restate the thesis's own measurement while
appearing to add something -- exactly the kind of number that looks like evidence and is not.

Window accuracy is still reported, but as a *cost* line rather than a result: the claim D6 makes
is that it buys bout structure nearly for free, and that claim is falsifiable only if the price is
stated.
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path

import numpy as np
import pytest

from app.domain.bouts import build_bouts
from app.domain.calibration import restrict_to_calibrated
from app.domain.features import extract_freq72
from app.domain.montage import MONTAGE
from app.domain.normalisation import zscore_envelopes, zscore_features
from app.domain.signal import bandpass_filter, linear_envelope
from app.domain.smoothing import enforce_minimum_dwell, majority_vote_smooth
from app.domain.windowing import STEP_SAMPLES, WINDOW_SAMPLES, sliding_windows
from app.serving.onnx_predictor import CLASSES, load_ensemble

ARTEFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts"
DEMO_DIR = ARTEFACT_DIR / "demo"

#: The three subjects held out of the deployment models' training set (SRS §6).
HELD_OUT = ("Sub10", "Sub13", "Sub22")

pytestmark = pytest.mark.skipif(
    not (ARTEFACT_DIR / "svm_freq72.onnx").exists()
    or not (DEMO_DIR / "demo_Sub10_truth.csv").exists(),
    reason="ONNX artefacts or demo recordings not present under backend/artifacts/",
)

FLAG_KWARGS = {"dns_wak_margin": 0.15, "low_confidence_threshold": 0.60}


def _load_session(path: Path) -> np.ndarray:
    with gzip.open(path, "rt") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        columns = [header.index(channel) for channel in MONTAGE]
        return np.array([[float(row[i]) for i in columns] for row in reader], dtype=np.float64)


def _load_truth(path: Path) -> list[tuple[str, int, int]]:
    with open(path) as fh:
        return [
            (r["task"], int(r["start_sample"]), int(r["end_sample"])) for r in csv.DictReader(fh)
        ]


def _true_window_labels(truth: list[tuple[str, int, int]], n_windows: int) -> np.ndarray:
    """A window's true class is the task covering the most of its samples.

    Majority overlap rather than the centre sample: a 250 ms window straddling a task boundary
    should be attributed to whichever task actually dominates it, and the centre-sample rule
    would assign a window that is 60% walking to stair ascent on the strength of one sample.
    """
    labels = np.empty(n_windows, dtype=np.int64)
    for w in range(n_windows):
        lo, hi = w * STEP_SAMPLES, w * STEP_SAMPLES + WINDOW_SAMPLES
        best_class, best_overlap = -1, 0
        for task, start, end in truth:
            overlap = max(0, min(hi, end) - max(lo, start))
            if overlap > best_overlap:
                best_class, best_overlap = CLASSES.index(task), overlap
        labels[w] = best_class
    return labels


def _runs(labels: np.ndarray) -> list[tuple[int, int, int]]:
    """``[(start, end, class_index), ...]``. Adjacent same-label truth rows merge, as they must:
    two consecutive sit-to-stand blocks are one bout to a reviewer, not two."""
    if labels.size == 0:
        return []
    cuts = np.flatnonzero(labels[1:] != labels[:-1]) + 1
    bounds = [0, *cuts.tolist(), labels.size]
    return [(bounds[i], bounds[i + 1], int(labels[bounds[i]])) for i in range(len(bounds) - 1)]


def _coherence(bouts, true_runs: list[tuple[int, int, int]]) -> dict[str, float]:
    fragments, cleanly = [], 0
    for start, end, class_index in true_runs:
        overlapping = [b for b in bouts if b.start_window < end and b.end_window > start]
        fragments.append(len(overlapping))
        dominant = [
            b
            for b in overlapping
            if (min(end, b.end_window) - max(start, b.start_window)) >= 0.5 * (end - start)
            and CLASSES.index(b.task) == class_index
        ]
        if len(overlapping) == 1 and len(dominant) == 1:
            cleanly += 1
    return {
        "bouts": float(len(bouts)),
        "fragments_per_true_bout": float(np.mean(fragments)) if fragments else float("nan"),
        "cleanly_recovered": float(cleanly),
    }


def _segment(subject: str) -> dict[str, object]:
    """One subject through the real pipeline, stopping at bouts, both with and without D6."""
    signal = _load_session(DEMO_DIR / f"demo_{subject}_session.csv.gz")
    truth = _load_truth(DEMO_DIR / f"demo_{subject}_truth.csv")

    filtered = bandpass_filter(signal)
    envelope = linear_envelope(filtered)
    features = zscore_features(extract_freq72(np.ascontiguousarray(sliding_windows(filtered))))
    envelopes = zscore_envelopes(np.ascontiguousarray(sliding_windows(envelope).transpose(0, 2, 1)))

    ensemble = load_ensemble(ARTEFACT_DIR)
    # Every task calibrated: D5's restriction is held constant so it cannot confound the
    # comparison -- the only thing that differs between the two arms is D6 itself.
    probabilities = restrict_to_calibrated(
        ensemble.predict(features, envelopes).probabilities, CLASSES
    )

    unsmoothed = probabilities.argmax(axis=1)
    smoothed = enforce_minimum_dwell(majority_vote_smooth(unsmoothed))

    true_labels = _true_window_labels(truth, unsmoothed.size)
    true_runs = _runs(true_labels)

    return {
        "subject": subject,
        "windows": int(unsmoothed.size),
        "true_bouts": len(true_runs),
        "unsmoothed": _coherence(
            build_bouts(f"{subject}-unsmoothed", unsmoothed, probabilities, **FLAG_KWARGS),
            true_runs,
        ),
        "smoothed": _coherence(
            build_bouts(f"{subject}-smoothed", smoothed, probabilities, **FLAG_KWARGS),
            true_runs,
        ),
        "accuracy_unsmoothed": float((unsmoothed == true_labels).mean()),
        "accuracy_smoothed": float((smoothed == true_labels).mean()),
    }


def _pooled(measurement: list[dict[str, object]], arm: str, key: str) -> float:
    return sum(r[arm][key] for r in measurement)


def _mean(measurement: list[dict[str, object]], arm: str, key: str) -> float:
    return float(np.mean([r[arm][key] for r in measurement]))


@pytest.fixture(scope="module")
def measurement() -> list[dict[str, object]]:
    return [_segment(subject) for subject in HELD_OUT]


def test_d6_reduces_fragmentation_and_the_table_is_printed(measurement, capsys):
    """The headline: D6 collapses an unusably fragmented segmentation into a reviewable one."""
    true_total = sum(r["true_bouts"] for r in measurement)
    windows = sum(r["windows"] for r in measurement)
    bouts_u, bouts_s = (
        _pooled(measurement, "unsmoothed", "bouts"),
        _pooled(measurement, "smoothed", "bouts"),
    )
    clean_u, clean_s = (
        _pooled(measurement, "unsmoothed", "cleanly_recovered"),
        _pooled(measurement, "smoothed", "cleanly_recovered"),
    )
    frag_u = _mean(measurement, "unsmoothed", "fragments_per_true_bout")
    frag_s = _mean(measurement, "smoothed", "fragments_per_true_bout")
    acc_u = float(np.mean([r["accuracy_unsmoothed"] for r in measurement]))
    acc_s = float(np.mean([r["accuracy_smoothed"] for r in measurement]))

    with capsys.disabled():
        print("\n\nD6 bout coherence -- smoothed vs unsmoothed, three held-out subjects")
        print(
            f"{'subject':8} {'windows':>8} {'true':>5} | {'bouts':>12} | "
            f"{'frags/bout':>20} | {'cleanly recovered':>19} | {'window acc':>16}"
        )
        for row in measurement:
            u, s = row["unsmoothed"], row["smoothed"]
            print(
                f"{row['subject']:8} {row['windows']:8d} {row['true_bouts']:5d} | "
                f"{int(u['bouts']):5d} -> {int(s['bouts']):3d} | "
                f"{u['fragments_per_true_bout']:9.2f} -> {s['fragments_per_true_bout']:7.2f} | "
                f"{int(u['cleanly_recovered']):8d} -> {int(s['cleanly_recovered']):6d} | "
                f"{row['accuracy_unsmoothed']:7.3f} -> {row['accuracy_smoothed']:5.3f}"
            )
        print(
            f"\nPOOLED  {true_total} true bouts over {windows} windows\n"
            f"  bouts produced       {int(bouts_u):4d} -> {int(bouts_s):4d}"
            f"   ({(1 - bouts_s / bouts_u) * 100:.1f}% fewer to review)\n"
            f"  fragments/true bout  {frag_u:4.2f} -> {frag_s:4.2f}\n"
            f"  cleanly recovered    {int(clean_u):4d} -> {int(clean_s):4d}"
            f"   of {true_total}  ({clean_u / true_total:.0%} -> {clean_s / true_total:.0%})\n"
            f"  window accuracy      {acc_u:.3f} -> {acc_s:.3f}"
            f"  ({(acc_s - acc_u) * 100:+.1f} pp -- the price)\n"
        )

    assert bouts_s < 0.25 * bouts_u, (
        f"D6 should collapse fragmentation by at least 4x; got {bouts_u:.0f} -> {bouts_s:.0f}"
    )


def test_d6_leaves_roughly_one_bout_per_true_bout(measurement):
    """Fragments per true bout is the metric a reviewer feels directly."""
    frag_u = _mean(measurement, "unsmoothed", "fragments_per_true_bout")
    frag_s = _mean(measurement, "smoothed", "fragments_per_true_bout")
    assert frag_u > 4.0, f"baseline should be badly over-segmented; got {frag_u:.2f}"
    assert frag_s < 2.0, f"D6 should land near one bout per true bout; got {frag_s:.2f}"


def test_d6_at_least_doubles_cleanly_recovered_bouts(measurement):
    """The strictest metric: bouts a reviewer could accept without editing."""
    clean_u = _pooled(measurement, "unsmoothed", "cleanly_recovered")
    clean_s = _pooled(measurement, "smoothed", "cleanly_recovered")
    assert clean_s >= 2 * clean_u, (
        f"D6 should at least double cleanly-recovered bouts; got {clean_u:.0f} -> {clean_s:.0f}"
    )


def test_the_structural_gain_does_not_cost_window_accuracy(measurement):
    """D6's claim is that bout structure is bought nearly for free. Bound the price at 1 pp.

    Not asserted as an improvement: smoothing *can* cost window accuracy, and on one of these
    three subjects it does. The defensible claim is that the cost is small and bounded, not that
    it is zero -- and a test asserting an improvement would fail honestly rather than usefully.
    """
    acc_u = float(np.mean([r["accuracy_unsmoothed"] for r in measurement]))
    acc_s = float(np.mean([r["accuracy_smoothed"] for r in measurement]))
    assert acc_s >= acc_u - 0.01, (
        f"D6 should cost at most 1 pp of window accuracy; got {acc_u:.3f} -> {acc_s:.3f}"
    )
