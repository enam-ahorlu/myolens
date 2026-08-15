import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { RequireAuth } from "./RequireAuth";

const mockUseAuth = vi.fn();
vi.mock("../lib/auth", () => ({
  useAuth: () => mockUseAuth(),
}));

function renderGuarded() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/login" element={<p>Login screen</p>} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <p>Protected content</p>
            </RequireAuth>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequireAuth", () => {
  it("shows a configuration message when Firebase has no config", () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, configured: false });
    renderGuarded();
    expect(screen.getByText(/firebase is not configured/i)).toBeInTheDocument();
  });

  it("shows a loading state before the first auth check resolves", () => {
    mockUseAuth.mockReturnValue({ user: null, loading: true, configured: true });
    renderGuarded();
    expect(screen.getByText(/checking your session/i)).toBeInTheDocument();
  });

  it("redirects to /login when nobody is signed in", () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, configured: true });
    renderGuarded();
    expect(screen.getByText("Login screen")).toBeInTheDocument();
  });

  it("renders the protected content once a user is signed in", () => {
    mockUseAuth.mockReturnValue({
      user: { email: "clinician@example.com" },
      loading: false,
      configured: true,
    });
    renderGuarded();
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });
});
