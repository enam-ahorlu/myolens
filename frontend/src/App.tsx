/**
 * Application shell.
 *
 * Currently a token and primitive check rather than a screen: it proves the design system
 * resolves in a real browser build before any workflow is wired to it. The screens themselves
 * arrive next, against these same primitives.
 *
 * The banner is placed here, once, at the top of the shell -- so it appears on every screen by
 * construction rather than by every screen remembering to include it.
 */
import { IntendedUseBanner } from "./components/IntendedUseBanner";
import { StatusChip } from "./components/StatusChip";
import { TaskBadge } from "./components/TaskBadge";
import { TASKS, confidenceOpacity } from "./lib/tasks";

const DEMO_BOUTS = [
  { task: "STDUP", seconds: 3.0, confidence: 0.94 },
  { task: "WAK", seconds: 3.0, confidence: 0.88 },
  { task: "UPS", seconds: 3.0, confidence: 0.79 },
  { task: "DNS", seconds: 3.0, confidence: 0.51 },
  { task: "STDUP", seconds: 3.0, confidence: 0.91 },
] as const;

export default function App() {
  return (
    <>
      <header className="top-bar">
        <span className="top-bar__mark">M</span>
        <span>
          <span className="top-bar__name">MyoLens</span>
          <br />
          <span className="top-bar__sub">Task-conditioned sEMG session analysis</span>
        </span>
      </header>

      <IntendedUseBanner />

      <main className="page">
        <section className="card">
          <h2 className="card__title">Movement classes</h2>
          <div className="row">
            {TASKS.map((task) => (
              <TaskBadge key={task} task={task} />
            ))}
          </div>
          <p className="muted">
            The only saturated fills in the product. Separation verified under deuteranopia and
            protanopia in CI, with a stricter floor on stair descent against level walking — the
            two classes the model confuses most.
          </p>
        </section>

        <section className="card">
          <h2 className="card__title">Status</h2>
          <div className="row">
            <StatusChip tone="verified" />
            <StatusChip tone="advisory" label="DNS excluded — not calibrated" />
            <StatusChip tone="refusal" label="Out of distribution" />
            <StatusChip tone="excluded" />
          </div>
          <p className="muted">
            A tint behind dark text, always with an icon and a word. Never a saturated block, so
            it never competes with a task colour for hue.
          </p>
        </section>

        <section className="card">
          <h2 className="card__title">Confidence as opacity</h2>
          <div className="row" style={{ gap: 0 }}>
            {DEMO_BOUTS.map((bout, i) => (
              <div
                key={i}
                style={{
                  width: 132,
                  height: 56,
                  display: "grid",
                  placeItems: "center",
                  color: "var(--text-on-fill)",
                  fontSize: "var(--text-label)",
                  fontWeight: 600,
                  backgroundColor: `var(--task-${bout.task.toLowerCase()})`,
                  opacity: confidenceOpacity(bout.confidence),
                }}
              >
                {bout.task} · {bout.confidence.toFixed(2)}
              </div>
            ))}
          </div>
          <p className="muted">
            Bouts the model is least sure of are literally fainter, so the eye finds the uncertain
            part of a segmentation before reading a number. Sequence taken from held-out
            subject 10.
          </p>
        </section>
      </main>
    </>
  );
}
