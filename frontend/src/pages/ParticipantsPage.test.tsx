import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { ParticipantsPage } from "./ParticipantsPage";

const listParticipants = vi.fn();
const createParticipant = vi.fn();

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      listParticipants: () => listParticipants(),
      createParticipant: (body: unknown) => createParticipant(body),
    },
  };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <ParticipantsPage />
    </MemoryRouter>,
  );
}

describe("ParticipantsPage", () => {
  beforeEach(() => {
    listParticipants.mockReset();
    createParticipant.mockReset();
  });

  it("lists the clinician's own participants", async () => {
    listParticipants.mockResolvedValue([
      {
        id: "p1",
        code: "P-001",
        age_band: "30_44",
        sex: "female",
        affected_side: "left",
        notes: "",
        created_by: "c1",
        difficulty_band: "typical",
      },
    ]);

    renderPage();

    expect(await screen.findByText("P-001")).toBeInTheDocument();
    expect(screen.getByText(/typical difficulty/)).toBeInTheDocument();
  });

  it("shows a message when there are no participants yet", async () => {
    listParticipants.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/no participants registered yet/i)).toBeInTheDocument();
  });

  it("surfaces a load failure instead of a blank list", async () => {
    listParticipants.mockRejectedValue(new ApiError(401, "unauthenticated", "Sign in required.", []));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(/sign in required/i);
  });

  it("registers a participant and refreshes the list", async () => {
    listParticipants.mockResolvedValueOnce([]).mockResolvedValueOnce([
      {
        id: "p2",
        code: "P-002",
        age_band: "18_29",
        sex: "male",
        affected_side: "right",
        notes: "",
        created_by: "c1",
        difficulty_band: null,
      },
    ]);
    createParticipant.mockResolvedValue({});

    renderPage();
    await screen.findByText(/no participants registered yet/i);

    fireEvent.change(screen.getByLabelText(/code/i), { target: { value: "P-002" } });
    fireEvent.click(screen.getByRole("button", { name: /register participant/i }));

    await waitFor(() => expect(createParticipant).toHaveBeenCalledWith(
      expect.objectContaining({ code: "P-002" }),
    ));
    expect(await screen.findByText("P-002")).toBeInTheDocument();
  });

  it("shows a validation error from the backend without clearing the form", async () => {
    listParticipants.mockResolvedValue([]);
    createParticipant.mockRejectedValue(
      new ApiError(422, "validation_failed", "The participant code must be 2-32 characters.", []),
    );

    renderPage();
    await screen.findByText(/no participants registered yet/i);

    fireEvent.change(screen.getByLabelText(/code/i), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /register participant/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/2-32 characters/);
  });
});
