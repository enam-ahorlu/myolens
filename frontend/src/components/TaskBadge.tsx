/**
 * A task badge -- the saturated fill that identifies a movement class.
 *
 * White text on the task colour. Every one of the four clears WCAG AA at that pairing, which is
 * asserted by `scripts/verify_palette.py` in CI rather than assumed here.
 *
 * The colour is always accompanied by the task name. Colour is the fast path, not the only path:
 * a reader scans the timeline by colour and confirms by reading, and a reader who cannot
 * distinguish two hues still gets the answer.
 */
import { TASK_COLOUR_VAR, TASK_LABEL, type Task } from "../lib/tasks";

export function TaskBadge({ task, abbreviated = false }: { task: Task; abbreviated?: boolean }) {
  return (
    <span
      className="task-badge"
      style={{ backgroundColor: TASK_COLOUR_VAR[task] }}
      title={TASK_LABEL[task]}
    >
      {abbreviated ? task : TASK_LABEL[task]}
    </span>
  );
}
