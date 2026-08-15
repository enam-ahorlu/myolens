/**
 * A route guard: redirects to `/login` until a clinician is signed in.
 *
 * Client-side only, and deliberately not the actual security boundary -- A1/A2/A3 are enforced
 * by the backend on every request (ADR-004). This exists purely so an unauthenticated visitor
 * sees the login screen instead of a page full of failed API calls.
 */

import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, configured } = useAuth();

  if (!configured) {
    return (
      <div className="page">
        <section className="card">
          <h2 className="card__title">Firebase is not configured</h2>
          <p className="muted">
            Copy <code>.env.example</code> to <code>.env.local</code> and fill in the{" "}
            <code>VITE_FIREBASE_*</code> values from the Firebase console (Project settings &gt;
            General &gt; Your apps &gt; Web app) before signing in.
          </p>
        </section>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="page">
        <p className="muted">Checking your session…</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
