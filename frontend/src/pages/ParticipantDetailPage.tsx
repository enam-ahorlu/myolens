/**
 * One participant: the record itself, plus edit (PATCH) and delete (DELETE) -- the two
 * frozen-surface routes (§10) that had backend support but no screen. Editing reuses the same
 * field set as registration (`ParticipantsPage`'s create form); delete asks for confirmation
 * once via the platform's own dialog, since undoing a wrong participant delete isn't possible
 * from here and a silent one-click delete would be a bad trade for that.
 */

import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  api,
  type AffectedSide,
  type AgeBand,
  type CalibrationOut,
  type Participant,
  type Sex,
} from "../lib/api";
import { CalibrationStatusBadge } from "./CalibrationPage";
import { TASKS, TASK_LABEL } from "../lib/tasks";

const AGE_BANDS: AgeBand[] = ["under_18", "18_29", "30_44", "45_59", "60_74", "75_plus"];
const SEXES: Sex[] = ["female", "male", "other", "undisclosed"];
const SIDES: AffectedSide[] = ["left", "right", "bilateral", "none"];

function formatBand(band: AgeBand): string {
  return band.replace("_", "-").replace("under-18", "under 18").replace("75-plus", "75+");
}

export function ParticipantDetailPage() {
  const { participantId } = useParams<{ participantId: string }>();
  const navigate = useNavigate();
  const [participant, setParticipant] = useState<Participant | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [calibration, setCalibration] = useState<CalibrationOut | null>(null);

  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState("");
  const [ageBand, setAgeBand] = useState<AgeBand>("30_44");
  const [sex, setSex] = useState<Sex>("undisclosed");
  const [side, setSide] = useState<AffectedSide>("none");
  const [notes, setNotes] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!participantId) return;
    api
      .getParticipant(participantId)
      .then(setParticipant)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "Could not load this participant."),
      );
    // B3: the four per-task calibration badges, so a clinician can see calibration readiness
    // without leaving the participant page. A brand-new participant has none yet -- that's
    // "not_calibrated", not a failure to report, same treatment as CalibrationPage gives it.
    api
      .getActiveCalibration(participantId)
      .then(setCalibration)
      .catch(() => setCalibration(null));
  }, [participantId]);

  function startEditing() {
    if (!participant) return;
    setCode(participant.code);
    setAgeBand(participant.age_band);
    setSex(participant.sex);
    setSide(participant.affected_side);
    setNotes(participant.notes);
    setSaveError(null);
    setEditing(true);
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!participantId) return;
    setSaveError(null);
    setSaving(true);
    try {
      const updated = await api.editParticipant(participantId, {
        code,
        age_band: ageBand,
        sex,
        affected_side: side,
        notes,
      });
      setParticipant(updated);
      setEditing(false);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Could not save these changes.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!participantId) return;
    if (!window.confirm("Delete this participant? This cannot be undone.")) return;
    setDeleteError(null);
    setDeleting(true);
    try {
      await api.deleteParticipant(participantId);
      navigate("/");
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Could not delete this participant.");
      setDeleting(false);
    }
  }

  return (
    <div className="page">
      <p>
        <Link to="/">&larr; All participants</Link>
      </p>
      {error && (
        <p role="alert" className="muted">
          {error}
        </p>
      )}
      {!participant && !error && <p className="muted">Loading…</p>}
      {participant && !editing && (
        <section className="card">
          <h2 className="card__title">{participant.code}</h2>
          <p className="muted">
            {participant.age_band.replace("_", "-")} · {participant.sex} ·{" "}
            {participant.affected_side}
            {participant.difficulty_band ? ` · ${participant.difficulty_band} difficulty` : ""}
          </p>
          {participant.notes && <p>{participant.notes}</p>}
          <div className="row" aria-label="Calibration status">
            {TASKS.map((task) => {
              const summary = calibration?.per_task[task];
              return (
                <span key={task} className="row" style={{ gap: "var(--space-2)" }}>
                  <span className="muted">{TASK_LABEL[task]}</span>
                  <CalibrationStatusBadge status={summary ? summary.status : "not_attempted"} />
                </span>
              );
            })}
          </div>
          <p>
            <Link to={`/participants/${participant.id}/calibration`}>Calibration &rarr;</Link>
          </p>
          <p>
            <Link to={`/participants/${participant.id}/session`}>Upload a session &rarr;</Link>
          </p>
          <div className="row">
            <button type="button" className="link-button" onClick={startEditing}>
              Edit
            </button>
            <button
              type="button"
              className="link-button"
              onClick={() => void handleDelete()}
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Delete"}
            </button>
          </div>
          {deleteError && (
            <p role="alert" className="muted">
              {deleteError}
            </p>
          )}
        </section>
      )}
      {participant && editing && (
        <section className="card">
          <h2 className="card__title">Edit {participant.code}</h2>
          <form onSubmit={(event) => void handleSave(event)}>
            <label htmlFor="edit-code">Code</label>
            <input id="edit-code" required value={code} onChange={(e) => setCode(e.target.value)} />
            <label htmlFor="edit-age-band">Age band</label>
            <select
              id="edit-age-band"
              value={ageBand}
              onChange={(e) => setAgeBand(e.target.value as AgeBand)}
            >
              {AGE_BANDS.map((band) => (
                <option key={band} value={band}>
                  {formatBand(band)}
                </option>
              ))}
            </select>
            <label htmlFor="edit-sex">Sex</label>
            <select id="edit-sex" value={sex} onChange={(e) => setSex(e.target.value as Sex)}>
              {SEXES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <label htmlFor="edit-side">Affected side</label>
            <select id="edit-side" value={side} onChange={(e) => setSide(e.target.value as AffectedSide)}>
              {SIDES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <label htmlFor="edit-notes">Notes</label>
            <textarea id="edit-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            {saveError && (
              <p role="alert" className="muted">
                {saveError}
              </p>
            )}
            <div className="row">
              <button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save changes"}
              </button>
              <button
                type="button"
                className="link-button"
                onClick={() => setEditing(false)}
                disabled={saving}
              >
                Cancel
              </button>
            </div>
          </form>
        </section>
      )}
    </div>
  );
}
