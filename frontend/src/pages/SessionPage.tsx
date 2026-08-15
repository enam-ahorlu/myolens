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

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  api,
  type BoutCorrectionOut,
  type BoutOut,
  type ExclusionReason,
  type SegmentationOut,
  type SessionOut,
} from "../lib/api";
import { TaskBadge } from "../components/TaskBadge";
import { StatusChip } from "../components/StatusChip";
import { TASKS, type Task } from "../lib/tasks";

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
      const signed = await api.signUpload("session", participantId, file.type || "text/csv");

      setPhase("uploading");
      await api.putToSignedUrl(signed.upload_url, file.type || "text/csv", file);

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

  function applySegmentation(result: SegmentationOut) {
    setSession(result.session);
    setBouts([...result.bouts].sort((a, b) => a.start_ms - b.start_ms));
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
      const sorted = kept.sort((a, b) => a.start_ms - b.start_ms);
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
            accept=".csv,text/csv"
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
          {locked && (
            <p className="muted">
              Results (metrics, export) are not wired to a screen yet -- still API-only.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
