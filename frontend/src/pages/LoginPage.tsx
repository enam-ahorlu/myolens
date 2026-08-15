/**
 * Sign-in. Email/password against Firebase Auth (ADR-004) -- MyoLens has no self-serve signup:
 * clinician accounts are provisioned out of band, so this screen only ever signs an existing
 * account in, never creates one.
 */

import { type FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

export function LoginPage() {
  const { user, signIn, configured } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    const redirectTo = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={redirectTo} replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signIn(email, password);
      navigate("/", { replace: true });
    } catch {
      // Firebase's own error messages are written for developers ("auth/wrong-password"), not
      // clinicians -- one deliberately vague message here rather than exposing which of email
      // or password was wrong, which would let a caller enumerate valid accounts.
      setError("Sign-in failed. Check your email and password and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <section className="card" style={{ maxWidth: 360 }}>
        <h2 className="card__title">Sign in</h2>
        {!configured && (
          <p className="muted">
            Firebase is not configured for this build -- see <code>.env.example</code>.
          </p>
        )}
        <form onSubmit={handleSubmit}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={!configured}
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={!configured}
          />
          {error && (
            <p role="alert" className="muted">
              {error}
            </p>
          )}
          <button type="submit" disabled={!configured || submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </div>
  );
}
