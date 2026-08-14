/**
 * The four movement classes, and how they are rendered.
 *
 * The order here is the model's output order and is frozen. It is duplicated from the backend
 * deliberately rather than fetched: a front end that discovers its own class list at runtime
 * cannot be type-checked against it, and a mismatch between the two would relabel every bout
 * consistently and silently.
 */

export const TASKS = ["DNS", "STDUP", "UPS", "WAK"] as const;

export type Task = (typeof TASKS)[number];

/** Human-readable names. Never abbreviated in prose, only in dense table cells. */
export const TASK_LABEL: Record<Task, string> = {
  DNS: "Stair descent",
  STDUP: "Sit to stand",
  UPS: "Stair ascent",
  WAK: "Level walking",
};

/**
 * CSS custom property holding each task's fill.
 *
 * A token name, never a hex. The values were derived and are gated by
 * `scripts/verify_palette.py`; hardcoding one here would route around that check.
 */
export const TASK_COLOUR_VAR: Record<Task, string> = {
  DNS: "var(--task-dns)",
  STDUP: "var(--task-stdup)",
  UPS: "var(--task-ups)",
  WAK: "var(--task-wak)",
};

/** Lowest opacity a bout block may be drawn at. Mirrors --confidence-opacity-floor. */
export const CONFIDENCE_OPACITY_FLOOR = 0.42;

/**
 * Map a model confidence to the opacity its bout is drawn at.
 *
 * Low-confidence bouts are literally fainter, so the eye finds the uncertain parts of a
 * segmentation before it reads a single number. The floor exists because a bout at zero opacity
 * would be invisible, and an invisible bout is one the reviewer cannot correct.
 *
 * Confidence outside [0, 1] is clamped rather than rejected: a rendering function is the wrong
 * place to discover a bad probability, and refusing to draw would hide the bout entirely.
 */
export function confidenceOpacity(confidence: number): number {
  const clamped = Math.min(1, Math.max(0, confidence));
  return CONFIDENCE_OPACITY_FLOOR + (1 - CONFIDENCE_OPACITY_FLOOR) * clamped;
}

/**
 * Order bouts for review: least certain first.
 *
 * Not chronological, and that is the point. A chronological queue spends the clinician's
 * attention uniformly across bouts the model is sure about. This ordering is the mechanism by
 * which a macro-F1 of 0.858 becomes a usable clinical workflow, so it lives in a named, tested
 * function rather than in a component's render.
 *
 * Sorting is stable on ties, so two equally uncertain bouts stay in time order relative to
 * each other.
 */
export function byReviewPriority<T extends { meanConfidence: number; flags?: string[] }>(
  bouts: readonly T[],
): T[] {
  return [...bouts].sort((a, b) => {
    const aFlagged = (a.flags?.length ?? 0) > 0;
    const bFlagged = (b.flags?.length ?? 0) > 0;
    if (aFlagged !== bFlagged) return aFlagged ? -1 : 1;
    return a.meanConfidence - b.meanConfidence;
  });
}
