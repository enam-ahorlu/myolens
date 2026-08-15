import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { ParticipantDetailPage } from "./ParticipantDetailPage";

const getParticipant = vi.fn();
const editParticipant = vi.fn();
const deleteParticipant = vi.fn();
const getActiveCalibration = vi.fn();
const navigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      getParticipant: (id: string) => getParticipant(id),
      editParticipant: (id: string, body: unknown) => editParticipant(id, body),
      deleteParticipant: (id: string) => deleteParticipant(id),
      getActiveCalibration: (id: string) => getActiveCalibration(id),
    },
  };
});

const PARTICIPANT = {
  id: "p1",
  code: "P-001",
  age_band: "30_44" as const,
  sex: "female" as const,
  affected_side: "left" as const,
  notes: "Some notes.",
  created_by: "clinician1",
  difficulty_band: "typical",
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/participants/p1"]}>
      <Routes>
        <Route path="/participants/:participantId" element={<ParticipantDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ParticipantDetailPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    getParticipant.mockReset();
    editParticipant.mockReset();
    deleteParticipant.mockReset();
    getActiveCalibration.mockReset();
    getActiveCalibration.mockRejectedValue(
      new ApiError(404, "not_calibrated", "No calibration on record.", []),
    );
    navigate.mockReset();
  });

  it("renders the participant record", async () => {
    getParticipant.mockResolvedValue(PARTICIPANT);
    renderPage();
    expect(await screen.findByText("P-001")).toBeInTheDocument();
    expect(screen.getByText("Some notes.")).toBeInTheDocument();
  });

  it("shows the four per-task calibration badges (B3)", async () => {
    getParticipant.mockResolvedValue(PARTICIPANT);
    getActiveCalibration.mockResolvedValue({
      id: "cal1",
      participant_id: "p1",
      version: 1,
      active: true,
      ood_flag: false,
      difficulty_band: "typical",
      envelope_peak: [1, 1, 1, 1, 1, 1, 1, 1, 1],
      per_task: {
        DNS: { window_count: 30, block_count: 3, status: "calibrated", sufficient: true },
        STDUP: { window_count: 5, block_count: 1, status: "insufficient", sufficient: false },
      },
    });
    renderPage();

    const status = await screen.findByLabelText("Calibration status");
    expect(status).toHaveTextContent("Calibrated");
    expect(status).toHaveTextContent("Insufficient");
    // UPS/WAK never appeared in per_task at all -- still rendered, as not attempted.
    expect(status).toHaveTextContent("Not attempted");
  });

  it("edits a participant and shows the saved result", async () => {
    getParticipant.mockResolvedValue(PARTICIPANT);
    editParticipant.mockResolvedValue({ ...PARTICIPANT, code: "P-001-B", notes: "Updated." });
    renderPage();

    await screen.findByText("P-001");
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));

    const codeInput = screen.getByLabelText(/code/i);
    fireEvent.change(codeInput, { target: { value: "P-001-B" } });
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(editParticipant).toHaveBeenCalledWith("p1", {
        code: "P-001-B",
        age_band: "30_44",
        sex: "female",
        affected_side: "left",
        notes: "Some notes.",
      }),
    );
    expect(await screen.findByText("P-001-B")).toBeInTheDocument();
    expect(screen.getByText("Updated.")).toBeInTheDocument();
  });

  it("cancels editing without saving", async () => {
    getParticipant.mockResolvedValue(PARTICIPANT);
    renderPage();

    await screen.findByText("P-001");
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    expect(screen.getByRole("button", { name: /save changes/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByRole("button", { name: /save changes/i })).not.toBeInTheDocument();
    expect(editParticipant).not.toHaveBeenCalled();
  });

  it("deletes a participant after confirming, then navigates home", async () => {
    getParticipant.mockResolvedValue(PARTICIPANT);
    deleteParticipant.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    await screen.findByText("P-001");
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() => expect(deleteParticipant).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/"));
  });

  it("does not delete when the confirmation is declined", async () => {
    getParticipant.mockResolvedValue(PARTICIPANT);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();

    await screen.findByText("P-001");
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));

    expect(deleteParticipant).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("shows an error and keeps the record if deletion fails", async () => {
    getParticipant.mockResolvedValue(PARTICIPANT);
    deleteParticipant.mockRejectedValue(new ApiError(409, "conflict", "Cannot delete: sessions exist.", []));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    await screen.findByText("P-001");
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot delete/i);
    expect(navigate).not.toHaveBeenCalled();
  });
});
