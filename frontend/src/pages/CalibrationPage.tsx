/**
 * Calibration upload and status for one participant (SRS §4.2 C).
 *
 * The upload flow is three calls, not one: `signUpload` mints a V4 signed URL (ADR-002),
 * `putToSignedUrl` PUTs the CSV straight to the bucket (never through our own backend), and
 * `createCalibration` registers the now-landed object so the backend can parse it, assess
 * per-task sufficiency (C1/C2), derive the %CAL reference (C3), and run the out-of-distribution
 * guard (C4). A refused (out-of-distribution) calibration is still *retained* per the backend's
 * own error message, so a 422 here still refreshes the active-calibration view rather than being
 * treated as a plain failure with nothing to show.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, UPLOAD_ACCEPT, api, type CalibrationOut } from "../lib/api";
import { StatusChip, type StatusTone } from "../components/StatusChip";
import { TASKS, TASK_LABEL } from "../lib/tasks";

type Phase = "idle" | "signing" | "uploading" | "registering";

/** B3: four per-task calibration badges, sharing the same tinted-chip register every other
 * status in the product uses (StatusChip) rather than plain table text, so "calibrated" reads
 * the same way here as "verified" does on a bout. */
const CALIBRATION_STATUS: Record<string, { tone: StatusTone; label: string }> = {
  calibrated: { tone: "verified", label: "Calibrated" },
  insufficient: { tone: "advisory", label: "Insufficient" },
  not_attempted: { tone: "excluded", label: "Not attempted" },
};

export function CalibrationStatusBadge({ status }: { status: string }) {
  const entry = CALIBRATION_STATUS[status] ?? { tone: "excluded" as StatusTone, label: status };
  return <StatusChip tone={entry.tone} label={entry.label} />;
}

export function CalibrationPage() {
  const { participantId } = useParams<{ participantId: string }>();
  const [active, setActive] = useState<CalibrationOut | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitNotice, setSubmitNotice] = useState<string | null>(null);

  const loadActive = useCallback(() => {
    if (!participantId) return;
    api
      .getActiveCalibration(participantId)
      .then((record) => {
        setActive(record);
        setLoadError(null);
      })
      .catch((err: unknown) => {
        // No calibration yet is expected for a brand-new participant, not a failure to report.
        if (err instanceof ApiError && err.code === "not_calibrated") {
          setActive(null);
          setLoadError(null);
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : "Could not load calibration status.");
      });
  }, [participantId]);

  useEffect(() => {
    loadActive();
  }, [loadActive]);

  async function handleUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!participantId || !file) return;
    setSubmitError(null);
    setSubmitNotice(null);

    try {
      setPhase("signing");
      const contentType = api.contentTypeFor(file.name);
      const signed = await api.signUpload("calibration", participantId, contentType);

      setPhase("uploading");
      await api.putToSignedUrl(signed.upload_url, contentType, file);

      setPhase("registering");
      const record = await api.createCalibration(participantId, signed.object_name);
      setActive(record);
      setSubmitNotice(`Calibration v${record.version} registered.`);
      setFile(null);
    } catch (err) {
      if (err instanceof ApiError && err.code === "out_of_distribution") {
        // C4: retained, not discarded -- refresh so the flagged record is visible, but still
        // tell the clinician plainly why segmentation can't proceed on it.
        setSubmitError(err.message);
        loadActive();
      } else {
        setSubmitError(
          err instanceof ApiError ? err.message : "Calibration upload failed. Please try again.",
        );
      }
    } finally {
      setPhase("idle");
    }
  }

  const busy = phase !== "idle";

  return (
    <div className="page">
      <p>
        {participantId && <Link to={`/participants/${participantId}`}>&larr; Participant</Link>}
      </p>
      <h2 className="card__title">Calibration</h2>

      {loadError && (
        <p role="alert" className="muted">
          {loadError}
        </p>
      )}

      {active ? (
        <section className="card">
          <p>
            <strong>Version {active.version}</strong> · {active.difficulty_band} difficulty
            {active.ood_flag && (
              <>
                {" "}
                <span role="status" className="muted">
                  · flagged out-of-distribution; segmentation is refused on this version
                </span>
              </>
            )}
          </p>
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>Windows</th>
                <th>Blocks</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {TASKS.map((task) => {
                const summary = active.per_task[task];
                return (
                  <tr key={task}>
                    <td>{TASK_LABEL[task]}</td>
                    <td>{summary?.window_count ?? 0}</td>
                    <td>{summary?.block_count ?? 0}</td>
                    <td>
                      <CalibrationStatusBadge status={summary ? summary.status : "not_attempted"} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ) : (
        !loadError && <p className="muted">No calibration on record yet.</p>
      )}

      <section className="card">
        <h3 className="card__title">Upload a new calibration capture</h3>
        <p className="muted">
          A labelled CSV: the nine montage channels plus a <code>label</code> column, with several
          non-contiguous blocks per task. Uploading a new capture supersedes the current one. The
          previous version is kept, not deleted.
        </p>
        <form onSubmit={(event) => void handleUpload(event)}>
          <label htmlFor="calibration-file">Calibration CSV</label>
          <input
            id="calibration-file"
            type="file"
            accept={UPLOAD_ACCEPT}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            disabled={busy}
          />
          {submitError && (
            <p role="alert" className="muted">
              {submitError}
            </p>
          )}
          {submitNotice && <p role="status">{submitNotice}</p>}
          <button type="submit" disabled={!file || busy}>
            {phase === "idle" && "Upload"}
            {phase === "signing" && "Requesting upload URL…"}
            {phase === "uploading" && "Uploading…"}
            {phase === "registering" && "Registering…"}
          </button>
        </form>
      </section>
    </div>
  );
}
