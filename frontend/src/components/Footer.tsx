/**
 * The site footer (H1: "reachable from every page footer").
 *
 * Present on every screen, the same way `IntendedUseBanner` is: rendered once in `App.tsx`,
 * outside `RequireAuth`, so the link to the model card works before sign-in too -- the backend
 * route it points to is deliberately unauthenticated for exactly that reason.
 */

import { Link } from "react-router-dom";

export function Footer() {
  return (
    <footer className="footer">
      <Link to="/model-card">Model card</Link>
    </footer>
  );
}
