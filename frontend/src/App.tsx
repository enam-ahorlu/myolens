/**
 * Application shell and routing.
 *
 * The intended-use banner sits here, once, above every route -- so it is present on every screen
 * by construction (F3) rather than by every screen remembering to include it. `RequireAuth`
 * wraps every route except `/login`, so an unauthenticated visitor never sees a page's worth of
 * failed API calls before being redirected.
 */
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { IntendedUseBanner } from "./components/IntendedUseBanner";
import { RequireAuth } from "./components/RequireAuth";
import { AuthProvider, useAuth } from "./lib/auth";
import { CalibrationPage } from "./pages/CalibrationPage";
import { LoginPage } from "./pages/LoginPage";
import { ParticipantDetailPage } from "./pages/ParticipantDetailPage";
import { ParticipantsPage } from "./pages/ParticipantsPage";
import { SessionPage } from "./pages/SessionPage";

function TopBar() {
  const { user, signOut } = useAuth();
  return (
    <header className="top-bar">
      <span className="top-bar__mark">M</span>
      <span>
        <span className="top-bar__name">MyoLens</span>
        <br />
        <span className="top-bar__sub">Task-conditioned sEMG session analysis</span>
      </span>
      {user && (
        <nav className="top-bar__nav">
          <span className="muted" style={{ margin: 0 }}>
            {user.email}
          </span>
          <button type="button" className="link-button" onClick={() => void signOut()}>
            Sign out
          </button>
        </nav>
      )}
    </header>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <TopBar />
        <IntendedUseBanner />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <ParticipantsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/participants/:participantId"
            element={
              <RequireAuth>
                <ParticipantDetailPage />
              </RequireAuth>
            }
          />
          <Route
            path="/participants/:participantId/calibration"
            element={
              <RequireAuth>
                <CalibrationPage />
              </RequireAuth>
            }
          />
          <Route
            path="/participants/:participantId/session"
            element={
              <RequireAuth>
                <SessionPage />
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
