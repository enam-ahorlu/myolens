/**
 * Session upload and automatic segmentation for one participant (D1-D8, SRS §4.2 D).
 *
 * There is no "list sessions" route on the frozen API surface (§10) -- a session is reached by
 * the id its own creation returns, not browsed from a list. This screen therefore holds the
 * whole upload -> segment -> bout-summary flow as client-side state for one session at a time,
 * rather than a route keyed by a session id nothing can look up independently yet. Review
 * (relabel/split/merge/exclude/approve) and results (metrics/export) are the next screens to
 * hang off the session this creates.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type SegmentationOut, type SessionOut } from "../lib/api";
import { TaskBadge } from "../components/TaskBadge";
import { StatusChip } from "../components/StatusChip";
import type { Task } from "../lib/tasks";

type Phase = "idle" | "signing" | "uploading" | "registering" | "segmenting";

function isTask(value: string): value is Task {
  return value === "DNS" || value === "STDUP" || value === "UPS" || value === "WAK";
}

export function SessionPage() {
  const { participantId } = useParams<{ participantId: string }>();
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [session, setSession] = useState<SessionOut | null>(null);
  const [segmentation, setSegmentation] = useState<SegmentationOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const busy = phase !== "idle";

  async function handleUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!participantId || !file) return;
    setError(null);
    setSegmentation(null);

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

  async function handleSegment() {
    if (!session) return;
    setError(null);
    try {
      setPhase("segmenting");
      const result = await api.segmentSession(session.id);
      setSession(result.session);
      setSegmentation(result);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Segmentation failed. Please try again.",
      );
    } finally {
      setPhase("idle");
    }
  }

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
            {(phase === "idle" || phase === "segmenting") && "Upload"}
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
        </section>
      )}

      {segmentation && (
        <section className="card">
          <h3 className="card__title">Segmentation result</h3>
          <p className="muted">
            {segmentation.bouts.length} bout{segmentation.bouts.length === 1 ? "" : "s"} ·{" "}
            {segmentation.flagged_count} flagged for review
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
              </tr>
            </thead>
            <tbody>
              {segmentation.bouts.map((bout) => (
                <tr key={bout.id}>
                  <td>{isTask(bout.task) ? <TaskBadge task={bout.task} abbreviated /> : bout.task}</td>
                  <td>{(bout.start_ms / 1000).toFixed(2)}s</td>
                  <td>{(bout.end_ms / 1000).toFixed(2)}s</td>
                  <td>{bout.window_count}</td>
                  <td>{(bout.mean_confidence * 100).toFixed(0)}%</td>
                  <td>
                    {bout.flagged ? (
                      <StatusChip tone="advisory" label={bout.flag_reasons.join(", ") || "Flagged"} />
                    ) : (
                      <StatusChip tone="verified" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            Review (relabel, split, merge, exclude) and approval are not wired to a screen yet --
            still API-only.
          </p>
        </section>
      )}
    </div>
  );
}
