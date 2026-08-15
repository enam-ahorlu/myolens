/**
 * Session upload, automatic segmentation, and segmentation review for one participant
 * (D1-D8 and E3-E8, SRS §4.2 D/E).
 *
 * There is no "list sessions" route on the frozen API surface (§10) -- a session is reached by
 * the id its own creation returns, not browsed from a list. This screen therefore holds the
 * whole upload -> segment -> review -> approve flow as client-side state for one session at a
 * time, rather than a route keyed by a session id nothing can look up independently yet.
 * Results (metrics/export) is the next screen to hang off the session this creates.
 *
 * Corrections (relabel/split/merge/exclude) return only the bouts a single PATCH touched, plus
 * any id it removed (split adds one, merge removes one) -- `applyCorrection` reconciles that
 * into the full bout list locally rather than re-fetching, since there is no "list bouts" route
 * to re-fetch from.
 */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  UPLOAD_ACCEPT,
  api,
  type BoutCorrectionOut,
  type BoutOut,
  type ExclusionReason,
  type SegmentationOut,
  type SessionMetricsOut,
  type SessionOut,
} from "../lib/api";
import { SessionTimeline } from "../components/SessionTimeline";
import { TaskBadge } from "../components/TaskBadge";
import { StatusChip } from "../components/StatusChip";
import { TASKS, TASK_LABEL, byReviewPriority as sortByReviewPriority, type Task } from "../lib/tasks";

type Phase = "idle" | "signing" | "uploading" | "registering" | "segmenting" | "approving";

function isTask(value: string): value is Task {
  return (TASKS as readonly string[]).includes(value);
}

const EXCLUSION_REASONS: ExclusionReason[] = ["artefact", "transition", "unobserved"];

type ReviewOp = "relabel" | "split" | "merge" | "exclude";

function BoutRow({
  bout,
  otherBouts,
  disabled,
  onCorrect,
}: {
  bout: BoutOut;
  otherBouts: BoutOut[];
  disabled: boolean;
  onCorrect: (boutId: string, op: ReviewOp, value: string) => void;
}) {
  const [op, setOp] = useState<ReviewOp>("relabel");
  const [value, setValue] = useState("");

  const neighbours = otherBouts.filter((b) => !b.excluded);

  function currentDefault(nextOp: ReviewOp): string {
    if (nextOp === "relabel") return TASKS[0];
    if (nextOp === "exclude") return EXCLUSION_REASONS[0];
    if (nextOp === "merge") return neighbours[0]?.id ?? "";
    return "";
  }

  return (
    <tr aria-label={`Bout ${bout.id}`}>
      <td>{isTask(bout.task) ? <TaskBadge task={bout.task} abbreviated /> : bout.task}</td>
      <td>{(bout.start_ms / 1000).toFixed(2)}s</td>
      <td>{(bout.end_ms / 1000).toFixed(2)}s</td>
      <td>{bout.window_count}</td>
      <td>{(bout.mean_confidence * 100).toFixed(0)}%</td>
      <td>
        {bout.excluded ? (
          <StatusChip tone="excluded" label={bout.exclusion_reason ?? "Excluded"} />
        ) : bout.flagged ? (
          <StatusChip tone="advisory" label={bout.flag_reasons.join(", ") || "Flagged"} />
        ) : (
          <StatusChip tone="verified" />
        )}
        {bout.corrected && <span className="muted"> (corrected)</span>}
      </td>
      <td>
        {!disabled && !bout.excluded && (
          <div className="row">
            <label htmlFor={`op-${bout.id}`} className="visually-hidden">
              Action for bout {bout.id}
            </label>
            <select
              id={`op-${bout.id}`}
              value={op}
              onChange={(event) => {
                const nextOp = event.target.value as ReviewOp;
                setOp(nextOp);
                setValue(currentDefault(nextOp));
              }}
            >
              <option value="relabel">Relabel</option>
              <option value="split">Split</option>
              <option value="merge">Merge</option>
              <option value="exclude">Exclude</option>
            </select>

            {op === "relabel" && (
              <select
                aria-label={`Relabel task for bout ${bout.id}`}
                value={value || TASKS[0]}
                onChange={(event) => setValue(event.target.value)}
              >
                {TASKS.map((task) => (
                  <option key={task} value={task}>
                    {task}
                  </option>
                ))}
              </select>
            )}

            {op === "split" && (
              <input
                aria-label={`Split at window for bout ${bout.id}`}
                type="number"
                min={bout.window_count > 1 ? 1 : undefined}
                value={value}
                onChange={(event) => setValue(event.target.value)}
                placeholder="window #"
              />
            )}

            {op === "merge" && (
              <select
                aria-label={`Merge with neighbour bout ${bout.id}`}
                value={value || neighbours[0]?.id || ""}
                onChange={(event) => setValue(event.target.value)}
                disabled={neighbours.length === 0}
              >
                {neighbours.length === 0 && <option value="">no adjacent bout</option>}
                {neighbours.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.task} @ {(n.start_ms / 1000).toFixed(2)}s
                  </option>
                ))}
              </select>
            )}

            {op === "exclude" && (
              <select
                aria-label={`Exclusion reason for bout ${bout.id}`}
                value={value || EXCLUSION_REASONS[0]}
                onChange={(event) => setValue(event.target.value)}
              >
                {EXCLUSION_REASONS.map((reason) => (
                  <option key={reason} value={reason}>
                    {reason}
                  </option>
                ))}
              </select>
            )}

            <button
              type="button"
              className="link-button"
              onClick={() => onCorrect(bout.id, op, value || currentDefault(op))}
            >
              Apply
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

function fmt(value: number | null, decimals = 1): string {
  return value == null ? "—" : value.toFixed(decimals);
}

function fmtCci(cci: SessionMetricsOut["tasks"][number]["cci_knee"]): string {
  if (cci.value == null) return `— (${cci.windows_used}/${cci.windows_total} windows)`;
  return `${cci.value.toFixed(2)} (${cci.windows_used}/${cci.windows_total} windows)`;
}

/** Results: the §3.3 metric set (F1) plus the PDF export (G1) -- reachable only once a session
 * is approved, since approval is the explicit gate before any metric exists (E7). */
function ResultsSection({ sessionId }: { sessionId: string }) {
  const [metrics, setMetrics] = useState<SessionMetricsOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getSessionMetrics(sessionId)
      .then((result) => {
        if (!cancelled) setMetrics(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not load metrics.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function handleExport() {
    setError(null);
    try {
      setExporting(true);
      const blob = await api.exportSession(sessionId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `myolens-session-${sessionId}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Export failed. Please try again.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="card">
      <h3 className="card__title">Results</h3>
      {error && (
        <p role="alert" className="muted">
          {error}
        </p>
      )}
      {!metrics && !error && <p className="muted">Loading…</p>}
      {metrics && (
        <>
          <p className="muted">
            {metrics.flagged_count} bout{metrics.flagged_count === 1 ? "" : "s"} flagged ·{" "}
            {metrics.tasks.length} task{metrics.tasks.length === 1 ? "" : "s"} with approved data
          </p>
          {metrics.tasks.length === 0 && (
            <p className="muted">No task had any non-excluded bout -- nothing to report.</p>
          )}
          {metrics.tasks.map((task) => (
            <div key={task.task} className="card" style={{ marginTop: "var(--space-4)" }}>
              <h4 style={{ margin: 0 }}>
                {isTask(task.task) ? <TaskBadge task={task.task} /> : task.task}
                {isTask(task.task) && <span className="muted"> {TASK_LABEL[task.task]}</span>}
              </h4>
              <table>
                <tbody>
                  <tr>
                    <th>Bouts</th>
                    <td>
                      {task.bout_count} · {fmt(task.bout_duration_total_s, 1)}s total
                    </td>
                  </tr>
                  <tr>
                    <th>Model confidence (pre-correction)</th>
                    <td>{fmt(task.model_confidence_mean * 100, 0)}%</td>
                  </tr>
                  <tr>
                    <th>Correction rate</th>
                    <td>{fmt(task.correction_rate_pct, 1)}%</td>
                  </tr>
                  <tr>
                    <th>CCI (knee)</th>
                    <td>{fmtCci(task.cci_knee)}</td>
                  </tr>
                  <tr>
                    <th>CCI (ankle)</th>
                    <td>{fmtCci(task.cci_ankle)}</td>
                  </tr>
                </tbody>
              </table>
              <table>
                <thead>
                  <tr>
                    <th>Channel</th>
                    <th>Amp mean (%CAL)</th>
                    <th>Amp peak (%CAL)</th>
                    <th>Duty cycle (%)</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.channels.map((channel, index) => (
                    <tr key={channel}>
                      <td>{channel}</td>
                      <td>{fmt(task.amp_mean[index])}</td>
                      <td>{fmt(task.amp_peak[index])}</td>
                      <td>{fmt(task.duty_cycle[index])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          <p>
            <button type="button" onClick={() => void handleExport()} disabled={exporting}>
              {exporting ? "Preparing PDF…" : "Download PDF report"}
            </button>
          </p>
        </>
      )}
    </section>
  );
}

export function SessionPage() {
  const { participantId } = useParams<{ participantId: string }>();
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [session, setSession] = useState<SessionOut | null>(null);
  const [bouts, setBouts] = useState<BoutOut[]>([]);
  const [flaggedCount, setFlaggedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const busy = phase !== "idle";

  async function handleUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!participantId || !file) return;
    setError(null);
    setNotice(null);
    setBouts([]);

    try {
      setPhase("signing");
      const contentType = api.contentTypeFor(file.name);
      const signed = await api.signUpload("session", participantId, contentType);

      setPhase("uploading");
      await api.putToSignedUrl(signed.upload_url, contentType, file);

      setPhase("registering");
      const created = await api.createSession(participantId, signed.object_name);
      setSession(created);
      setFile(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Session upload failed. Please try again.");
    } finally {
      setPhase("idle");
    }
  }

  /** E2: least-certain first, using the single tested definition of "review priority" in
   * `lib/tasks.ts` (also the one E1's timeline legend and F-07's flagging both refer back to)
   * rather than a second, parallel ordering living only in this file. Excluded bouts (nothing
   * left to review) are held out and appended at the end, sorted by start time, since
   * `byReviewPriority` itself has no notion of "excluded." */
  function applyReviewOrder(bouts: BoutOut[]): BoutOut[] {
    const excluded = bouts.filter((b) => b.excluded).sort((a, b) => a.start_ms - b.start_ms);
    const active = bouts.filter((b) => !b.excluded);
    const prioritized = sortByReviewPriority(
      active.map((bout) => ({ bout, meanConfidence: bout.mean_confidence, flags: bout.flag_reasons })),
    ).map((entry) => entry.bout);
    return [...prioritized, ...excluded];
  }

  function applySegmentation(result: SegmentationOut) {
    setSession(result.session);
    setBouts(applyReviewOrder(result.bouts));
    setFlaggedCount(result.flagged_count);
  }

  function applyCorrection(result: BoutCorrectionOut) {
    setBouts((prev) => {
      const kept = prev.filter((b) => !result.removed_bout_ids.includes(b.id));
      for (const updated of result.bouts) {
        const index = kept.findIndex((b) => b.id === updated.id);
        if (index >= 0) kept[index] = updated;
        else kept.push(updated);
      }
      const sorted = applyReviewOrder(kept);
      setFlaggedCount(sorted.filter((b) => b.flagged && !b.excluded).length);
      return sorted;
    });
  }

  async function handleSegment() {
    if (!session) return;
    setError(null);
    setNotice(null);
    try {
      setPhase("segmenting");
      const result = await api.segmentSession(session.id);
      applySegmentation(result);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Segmentation failed. Please try again.",
      );
    } finally {
      setPhase("idle");
    }
  }

  async function handleCorrect(boutId: string, op: ReviewOp, value: string) {
    if (!session) return;
    setError(null);
    setNotice(null);
    try {
      const result = await api.correctBout(
        session.id,
        boutId,
        op === "relabel"
          ? { op, task: value }
          : op === "split"
            ? { op, at_window: Number(value) }
            : op === "merge"
              ? { op, neighbor_bout_id: value }
              : { op, reason: value as ExclusionReason },
      );
      applyCorrection(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That correction failed. Please try again.");
    }
  }

  async function handleApprove() {
    if (!session) return;
    setError(null);
    setNotice(null);
    try {
      setPhase("approving");
      const updated = await api.approveSession(session.id);
      setSession(updated);
      setNotice("Segmentation approved. Metrics and export can now be computed.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Approval failed. Please try again.");
    } finally {
      setPhase("idle");
    }
  }

  const locked = session?.status === "approved";

  return (
    <div className="page">
      <p>
        {participantId && <Link to={`/participants/${participantId}`}>&larr; Participant</Link>}
      </p>
      <h2 className="card__title">Session</h2>

      {error && (
        <p role="alert" className="muted">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}

      <section className="card">
        <h3 className="card__title">Upload a recording</h3>
        <p className="muted">
          A raw sEMG recording CSV, up to ten minutes, matching the nine-channel montage. Once
          registered you can run automatic segmentation on it.
        </p>
        <form onSubmit={(event) => void handleUpload(event)}>
          <label htmlFor="session-file">Session recording CSV</label>
          <input
            id="session-file"
            type="file"
            // Gzip belongs here because the rest of this component already knows about it:
            // contentTypeFor() returns application/gzip for a .gz name, the signed URL is minted
            // for that type, and the backend reads either. Omitting it here made the file picker
            // grey out the only recordings the product ships.
            accept={UPLOAD_ACCEPT}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            disabled={busy}
          />
          <button type="submit" disabled={!file || busy}>
            {phase === "signing" && "Requesting upload URL…"}
            {phase === "uploading" && "Uploading…"}
            {phase === "registering" && "Registering…"}
            {(phase === "idle" || phase === "segmenting" || phase === "approving") && "Upload"}
          </button>
        </form>
      </section>

      {session && (
        <section className="card">
          <h3 className="card__title">Session {session.id}</h3>
          <p className="muted">
            {session.duration_seconds.toFixed(1)}s · {session.sample_count} samples · status:{" "}
            {session.status}
            {session.window_count != null && ` · ${session.window_count} windows`}
          </p>
          {session.status === "uploaded" && (
            <button type="button" onClick={() => void handleSegment()} disabled={busy}>
              {phase === "segmenting" ? "Segmenting…" : "Run segmentation"}
            </button>
          )}
          {session.status === "segmented" && bouts.length > 0 && (
            <button type="button" onClick={() => void handleApprove()} disabled={busy}>
              {phase === "approving" ? "Approving…" : "Approve segmentation"}
            </button>
          )}
        </section>
      )}

      {bouts.length > 0 && (
        <section className="card">
          <h3 className="card__title">
            {locked ? "Approved segmentation" : "Segmentation result -- review"}
          </h3>
          <p className="muted">
            {bouts.length} bout{bouts.length === 1 ? "" : "s"} · {flaggedCount} flagged for review
            {locked && " · locked, no further corrections"}
          </p>
          <SessionTimeline bouts={bouts} />
          {!locked && bouts.length > 1 && (
            <p className="muted" role="note">
              Sorted least-certain first, so the bouts most worth a second look come before the
              ones the model is already confident about.
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>Start</th>
                <th>End</th>
                <th>Windows</th>
                <th>Confidence</th>
                <th>Status</th>
                <th>Correct</th>
              </tr>
            </thead>
            <tbody>
              {bouts.map((bout) => (
                <BoutRow
                  key={bout.id}
                  bout={bout}
                  otherBouts={bouts.filter((b) => b.id !== bout.id)}
                  disabled={locked}
                  onCorrect={(boutId, op, value) => void handleCorrect(boutId, op, value)}
                />
              ))}
            </tbody>
          </table>
          {!locked && (
            <p className="muted">
              Relabel rejects a task this participant isn't calibrated for. Split takes an
              absolute window index; merge only works with an adjacent, same-status bout.
              Approving locks the segmentation -- no further corrections after that (E7).
            </p>
          )}
        </section>
      )}

      {locked && session && <ResultsSection sessionId={session.id} />}
    </div>
  );
}
