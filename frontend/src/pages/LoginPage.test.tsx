import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";

const mockUseAuth = vi.fn();
vi.mock("../lib/auth", () => ({
  useAuth: () => mockUseAuth(),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
  });

  it("disables the form when Firebase is not configured", () => {
    mockUseAuth.mockReturnValue({ user: null, signIn: vi.fn(), configured: false });
    renderPage();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeDisabled();
  });

  it("shows a vague failure message rather than which field was wrong", async () => {
    const signIn = vi.fn().mockRejectedValue(new Error("auth/wrong-password"));
    mockUseAuth.mockReturnValue({ user: null, signIn, configured: true });
    renderPage();

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "c@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/sign-in failed/i);
    expect(alert.textContent).not.toMatch(/wrong-password/);
  });

  it("redirects once a user is already signed in", () => {
    mockUseAuth.mockReturnValue({
      user: { email: "c@example.com" },
      signIn: vi.fn(),
      configured: true,
    });
    renderPage();
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });
});
