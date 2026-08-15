/**
 * One participant. Calibration and session upload/review/results (items still open on
 * HANDOFF_MYOLENS.md §7's frontend list) will hang off this screen; for now it shows the record
 * itself, which is enough to prove the detail route and A3 scoping work end to end.
 */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, type Participant } from "../lib/api";

export function ParticipantDetailPage() {
  const { participantId } = useParams<{ participantId: string }>();
  const [participant, setParticipant] = useState<Participant | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!participantId) return;
    api
      .getParticipant(participantId)
      .then(setParticipant)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "Could not load this participant."),
      );
  }, [participantId]);

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
      {participant && (
        <section className="card">
          <h2 className="card__title">{participant.code}</h2>
          <p className="muted">
            {participant.age_band.replace("_", "-")} · {participant.sex} ·{" "}
            {participant.affected_side}
            {participant.difficulty_band ? ` · ${participant.difficulty_band} difficulty` : ""}
          </p>
          {participant.notes && <p>{participant.notes}</p>}
          <p>
            <Link to={`/participants/${participant.id}/calibration`}>Calibration &rarr;</Link>
          </p>
          <p className="muted">
            Session upload, segmentation review, and results are not wired to this screen yet --
            still API-only (see HANDOFF_MYOLENS.md §7).
          </p>
        </section>
      )}
    </div>
  );
}
