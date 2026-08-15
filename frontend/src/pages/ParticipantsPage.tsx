/**
 * Participants (B1/B2): list the calling clinician's own participants (A3 -- the backend scopes
 * this, not this component) and register a new one.
 *
 * The code field is deliberately unlabelled as anything but "code" -- `app.domain.participants`
 * rejects a name-shaped value, and the placeholder here says so before a clinician finds out
 * from a 422.
 */

import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type AffectedSide, type AgeBand, type Participant, type Sex } from "../lib/api";

const AGE_BANDS: AgeBand[] = ["under_18", "18_29", "30_44", "45_59", "60_74", "75_plus"];
const SEXES: Sex[] = ["female", "male", "other", "undisclosed"];
const SIDES: AffectedSide[] = ["left", "right", "bilateral", "none"];

function formatBand(band: AgeBand): string {
  return band.replace("_", "-").replace("under-18", "under 18").replace("75-plus", "75+");
}

export function ParticipantsPage() {
  const [participants, setParticipants] = useState<Participant[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [code, setCode] = useState("");
  const [ageBand, setAgeBand] = useState<AgeBand>("30_44");
  const [sex, setSex] = useState<Sex>("undisclosed");
  const [side, setSide] = useState<AffectedSide>("none");
  const [notes, setNotes] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function refresh() {
    try {
      setParticipants(await api.listParticipants());
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load participants.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await api.createParticipant({ code, age_band: ageBand, sex, affected_side: side, notes });
      setCode("");
      setNotes("");
      await refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not register the participant.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page page--split">
      <section className="card">
        <h2 className="card__title">Register a participant</h2>
        <form onSubmit={handleCreate}>
          <label htmlFor="code">Code</label>
          <input
            id="code"
            required
            placeholder="e.g. P-014 -- pseudonymous, never a name"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <label htmlFor="age-band">Age band</label>
          <select id="age-band" value={ageBand} onChange={(e) => setAgeBand(e.target.value as AgeBand)}>
            {AGE_BANDS.map((band) => (
              <option key={band} value={band}>
                {formatBand(band)}
              </option>
            ))}
          </select>
          <label htmlFor="sex">Sex</label>
          <select id="sex" value={sex} onChange={(e) => setSex(e.target.value as Sex)}>
            {SEXES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <label htmlFor="side">Affected side</label>
          <select id="side" value={side} onChange={(e) => setSide(e.target.value as AffectedSide)}>
            {SIDES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <label htmlFor="notes">Notes</label>
          <textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          {formError && (
            <p role="alert" className="muted">
              {formError}
            </p>
          )}
          <button type="submit" disabled={submitting}>
            {submitting ? "Registering…" : "Register participant"}
          </button>
        </form>
      </section>

      <section className="card">
        <h2 className="card__title">My participants</h2>
        {loadError && (
          <p role="alert" className="muted">
            {loadError}
          </p>
        )}
        {participants === null && !loadError && <p className="muted">Loading…</p>}
        {participants?.length === 0 && <p className="muted">No participants registered yet.</p>}
        {participants && participants.length > 0 && (
          <ul aria-label="Participants">
            {participants.map((p) => (
              <li key={p.id}>
                <Link to={`/participants/${p.id}`}>{p.code}</Link>{" "}
                <span className="muted">
                  {formatBand(p.age_band)} · {p.sex} · {p.affected_side}
                  {p.difficulty_band ? ` · ${p.difficulty_band} difficulty` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
