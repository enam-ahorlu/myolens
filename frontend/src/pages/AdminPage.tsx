/**
 * Admin: list every account and set its role (A4, SRS §4.2 A).
 *
 * The backend is the actual authorisation boundary (`require_admin`, A2) -- this screen does not
 * try to duplicate that client-side. A clinician who reaches this route sees the same 403 the
 * API returns, worded the same way, rather than the page pretending the route doesn't exist.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type Clinician, type Role } from "../lib/api";

const ROLES: Role[] = ["clinician", "admin"];

export function AdminPage() {
  const [clinicians, setClinicians] = useState<Clinician[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingUid, setSavingUid] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listClinicians()
      .then((result) => {
        setClinicians(result);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "Could not load the account list."),
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRoleChange(uid: string, role: Role) {
    setError(null);
    setNotice(null);
    setSavingUid(uid);
    try {
      const updated = await api.setClinicianRole(uid, role);
      setClinicians((prev) => prev?.map((c) => (c.uid === uid ? updated : c)) ?? prev);
      setNotice(`${updated.email ?? updated.uid} is now ${updated.role}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that role change.");
    } finally {
      setSavingUid(null);
    }
  }

  return (
    <div className="page">
      <h2 className="card__title">Administration</h2>
      <p className="muted">
        Every account and its role. A role change takes effect the next time that clinician's
        session token refreshes, not immediately (A4).
      </p>

      {error && (
        <p role="alert" className="muted">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {!clinicians && !error && <p className="muted">Loading…</p>}

      {clinicians && (
        <section className="card">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {clinicians.map((clinician) => (
                <tr key={clinician.uid}>
                  <td>{clinician.email ?? clinician.uid}</td>
                  <td>
                    <label htmlFor={`role-${clinician.uid}`} className="visually-hidden">
                      Role for {clinician.email ?? clinician.uid}
                    </label>
                    <select
                      id={`role-${clinician.uid}`}
                      value={clinician.role}
                      disabled={savingUid === clinician.uid}
                      onChange={(event) =>
                        void handleRoleChange(clinician.uid, event.target.value as Role)
                      }
                    >
                      {ROLES.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{clinician.disabled ? "disabled" : "active"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
