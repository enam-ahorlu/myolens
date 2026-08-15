/**
 * The segmentation timeline (E1, SRS §4.2 E1): bouts coloured by task, confidence encoded as
 * opacity, flagged bouts visually marked.
 *
 * Deliberately a *supplement* to the bout table below it, not a replacement -- the same
 * discipline `TaskBadge` documents ("colour is the fast path, not the only path"). The
 * sortable/actionable review list is the table, not this.
 *
 * **Accessibility.** The track was previously `role="img"` with a single label, which collapses
 * it to a leaf in the accessibility tree and discards every child's `aria-label` -- so the
 * per-bout labels below were unreachable, and the docstring's claim that they carried the same
 * information to a non-sighted reader was false. It is a list, because that is what it is: an
 * ordered set of bouts. Each segment is a `listitem` carrying its own accessible name.
 *
 * There is deliberately **no keyboard handling**, and that is not an omission. The segments have
 * no behaviour -- no click handler, no selection, nothing to activate. WCAG 2.1.1 governs
 * *functionality*, and adding `tabIndex` to a non-interactive `div` would manufacture forty tab
 * stops that do nothing, which is worse for a keyboard user than none. Every action lives in the
 * table, which is reachable and operable in the ordinary way.
 *
 * Bounded by bout count, not window count: even a 10-minute, 4800-window session produces on
 * the order of tens of bouts (D6/D7 merge adjacent same-label windows first), so this renders a
 * few dozen DOM nodes, never thousands -- the "without lag" half of E1's acceptance criterion.
 */

import type { BoutOut } from "../lib/api";
import { TASK_COLOUR_VAR, TASK_LABEL, confidenceOpacity, type Task } from "../lib/tasks";

function isTask(value: string): value is Task {
  return value in TASK_COLOUR_VAR;
}

function fmtSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

export function SessionTimeline({ bouts }: { bouts: BoutOut[] }) {
  if (bouts.length === 0) return null;

  const durationMs = Math.max(...bouts.map((b) => b.end_ms));
  if (durationMs <= 0) return null;

  return (
    <div>
      <ol className="timeline-track" aria-label="Segmentation timeline, in recording order">
        {bouts.map((bout) => {
          const leftPct = (bout.start_ms / durationMs) * 100;
          const widthPct = Math.max(((bout.end_ms - bout.start_ms) / durationMs) * 100, 0.15);
          const label = isTask(bout.task) ? TASK_LABEL[bout.task] : bout.task;
          const confidencePct = Math.round(bout.mean_confidence * 100);
          const title = bout.excluded
            ? `${label}, ${fmtSeconds(bout.start_ms)}-${fmtSeconds(bout.end_ms)}, excluded (${bout.exclusion_reason ?? "excluded"})`
            : `${label}, ${fmtSeconds(bout.start_ms)}-${fmtSeconds(bout.end_ms)}, ${confidencePct}% confidence` +
              (bout.flagged ? ` -- flagged: ${bout.flag_reasons.join(", ")}` : "");

          return (
            <li
              key={bout.id}
              className={`timeline-bout${bout.flagged && !bout.excluded ? " timeline-bout--flagged" : ""}${bout.excluded ? " timeline-bout--excluded" : ""}`}
              title={title}
              aria-label={title}
              style={{
                left: `${leftPct}%`,
                width: `${widthPct}%`,
                backgroundColor: isTask(bout.task) ? TASK_COLOUR_VAR[bout.task] : "var(--border-strong)",
                opacity: bout.excluded ? undefined : confidenceOpacity(bout.mean_confidence),
              }}
            />
          );
        })}
      </ol>
      <p className="muted timeline-legend">
        Colour = task &middot; fainter = less certain &middot;{" "}
        <span className="timeline-legend__flag" aria-hidden="true" /> marked = flagged for review
        &middot; hatched = excluded
      </p>
    </div>
  );
}
