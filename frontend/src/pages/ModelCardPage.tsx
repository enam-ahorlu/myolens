/**
 * The model card (H1): version, SHA-256, training protocol, both accuracy regimes labelled,
 * held-out validation, montage, failure modes, intended use -- read from the backend's
 * `GET /v1/models/current`, which reads it in turn from the artefact directory's manifest so
 * this page can never drift from what is actually deployed.
 *
 * Deliberately outside `RequireAuth` (see `App.tsx`) and fetched with `auth: false`: it carries
 * no participant data, and the whole point of H1 is that provenance can be checked without
 * first signing in.
 */

import { useEffect, useState } from "react";
import { ApiError, api, type ModelCard } from "../lib/api";

export function ModelCardPage() {
  const [card, setCard] = useState<ModelCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setCard(await api.getModelCard());
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load the model card.");
      }
    })();
  }, []);

  return (
    <div className="page">
      <h2 className="card__title">Model card</h2>

      {error && (
        <p role="alert" className="muted">
          {error}
        </p>
      )}
      {!card && !error && <p className="muted">Loading…</p>}

      {card && (
        <>
          <section className="card">
            <h3 className="card__title">Intended use</h3>
            {card.intended_use.split("\n\n").map((paragraph, i) => (
              <p key={i}>{paragraph}</p>
            ))}
          </section>

          <section className="card">
            <h3 className="card__title">Active model</h3>
            <p className="muted">
              {card.active_predictor} &middot; {card.active_version}
            </p>
            <p className="muted" style={{ wordBreak: "break-all" }}>
              SHA-256: {card.active_sha256}
            </p>
          </section>

          <section className="card">
            <h3 className="card__title">Accuracy, both regimes</h3>
            <table>
              <thead>
                <tr>
                  <th>Regime</th>
                  <th>Macro-F1</th>
                  <th>Balanced accuracy</th>
                  <th>Windows evaluated</th>
                </tr>
              </thead>
              <tbody>
                {card.accuracy_regimes.map((regime) => (
                  <tr key={regime.predictor}>
                    <td>{regime.label}</td>
                    <td>{regime.macro_f1.toFixed(3)}</td>
                    <td>{regime.balanced_acc.toFixed(3)}</td>
                    <td>{regime.n_windows}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              Both figures are transductive, per-session held-out validation -- see "Held-out
              validation" below and FR-09.
            </p>
          </section>

          <section className="card">
            <h3 className="card__title">Held-out validation</h3>
            <p className="muted">
              {card.held_out_validation.training_subjects_n} training subjects, held out subjects{" "}
              {card.held_out_validation.holdout_subjects.join(", ")} &middot;{" "}
              {card.held_out_validation.n_windows} windows &middot; seed{" "}
              {card.held_out_validation.seed}
            </p>
          </section>

          <section className="card">
            <h3 className="card__title">Training protocol</h3>
            <p className="muted">
              Prepared {new Date(card.training_protocol.created_utc).toLocaleDateString()} &middot;{" "}
              {card.training_protocol.window_ms} ms window, {card.training_protocol.step_ms} ms
              step &middot; band-pass {card.training_protocol.bandpass_hz.join("-")} Hz, order{" "}
              {card.training_protocol.bandpass_order} &middot; {card.training_protocol.envelope_ms}{" "}
              ms envelope
            </p>
            <p className="muted">Normalisation: {card.training_protocol.normalisation_mode}</p>
          </section>

          <section className="card">
            <h3 className="card__title">Montage &amp; classes</h3>
            <p className="muted">Contract version {card.montage_contract_version}</p>
            <ul aria-label="Montage channels">
              {card.montage_channels.map((channel) => (
                <li key={channel}>{channel}</li>
              ))}
            </ul>
            <p className="muted">Classes: {card.classes.join(", ")}</p>
          </section>

          <section className="card">
            <h3 className="card__title">Known failure modes</h3>
            <ul aria-label="Failure modes">
              {card.failure_modes.map((mode, i) => (
                <li key={i}>{mode}</li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
