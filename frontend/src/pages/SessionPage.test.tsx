import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { SessionPage } from "./SessionPage";

const signUpload = vi.fn();
const putToSignedUrl = vi.fn();
const createSession = vi.fn();
const segmentSession = vi.fn();

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      signUpload: (kind: string, id: string, contentType: string) =>
        signUpload(kind, id, contentType),
      putToSignedUrl: (url: string, contentType: string, file: unknown) =>
        putToSignedUrl(url, contentType, file),
      createSession: (id: string, objectName: string) => createSession(id, objectName),
      segmentSession: (sessionId: string) => segmentSession(sessionId),
    },
  };
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/participants/p1/session"]}>
      <Routes>
        <Route path="/participants/:participantId/session" element={<SessionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function upload(file: File) {
  fireEvent.change(screen.getByLabelText(/session recording csv/i), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
}

describe("SessionPage", () => {
  beforeEach(() => {
    signUpload.mockReset();
    putToSignedUrl.mockReset();
    createSession.mockReset();
    segmentSession.mockReset();
  });

  it("uploads a recording through sign -> PUT -> register, then offers segmentation", async () => {
    signUpload.mockResolvedValue({
      object_name: "session/p1/abc.csv",
      upload_url: "https://storage.example/signed",
      method: "PUT",
      expires_in_seconds: 900,
    });
    putToSignedUrl.mockResolvedValue(undefined);
    createSession.mockResolvedValue({
      id: "s1",
      participant_id: "p1",
      status: "uploaded",
      sample_count: 100000,
      duration_seconds: 52.1,
      model_version: null,
      calibration_version: null,
      window_count: null,
    });

    renderPage();
    const file = new File(["Time\n"], "recording.csv", { type: "text/csv" });
    upload(file);

    await waitFor(() => expect(createSession).toHaveBeenCalledWith("p1", "session/p1/abc.csv"));
    expect(await screen.findByText(/session s1/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run segmentation/i })).toBeInTheDocument();
  });

  it("runs segmentation and shows the resulting bouts", async () => {
    signUpload.mockResolvedValue({
      object_name: "session/p1/abc.csv",
      upload_url: "https://storage.example/signed",
      method: "PUT",
      expires_in_seconds: 900,
    });
    putToSignedUrl.mockResolvedValue(undefined);
    createSession.mockResolvedValue({
      id: "s1",
      participant_id: "p1",
      status: "uploaded",
      sample_count: 100000,
      duration_seconds: 52.1,
      model_version: null,
      calibration_version: null,
      window_count: null,
    });
    segmentSession.mockResolvedValue({
      session: {
        id: "s1",
        participant_id: "p1",
        status: "segmented",
        sample_count: 100000,
        duration_seconds: 52.1,
        model_version: "ensemble-1.0.0",
        calibration_version: 2,
        window_count: 40,
      },
      bouts: [
        {
          id: "b1",
          task: "WAK",
          start_ms: 0,
          end_ms: 2000,
          window_count: 8,
          mean_confidence: 0.91,
          flagged: false,
          flag_reasons: [],
          excluded: false,
          exclusion_reason: null,
          corrected: false,
          original_task: null,
        },
        {
          id: "b2",
          task: "DNS",
          start_ms: 2000,
          end_ms: 3200,
          window_count: 5,
          mean_confidence: 0.4,
          flagged: true,
          flag_reasons: ["low_confidence"],
          excluded: false,
          exclusion_reason: null,
          corrected: false,
          original_task: null,
        },
      ],
      flagged_count: 1,
    });

    renderPage();
    upload(new File(["Time\n"], "recording.csv", { type: "text/csv" }));
    await screen.findByText(/session s1/i);

    fireEvent.click(screen.getByRole("button", { name: /run segmentation/i }));

    await waitFor(() => expect(segmentSession).toHaveBeenCalledWith("s1"));
    expect(await screen.findByText(/2 bouts/i)).toBeInTheDocument();
    expect(screen.getByText(/1 flagged for review/i)).toBeInTheDocument();
  });

  it("surfaces a not-calibrated refusal from segmentation", async () => {
    signUpload.mockResolvedValue({
      object_name: "session/p1/abc.csv",
      upload_url: "https://storage.example/signed",
      method: "PUT",
      expires_in_seconds: 900,
    });
    putToSignedUrl.mockResolvedValue(undefined);
    createSession.mockResolvedValue({
      id: "s1",
      participant_id: "p1",
      status: "uploaded",
      sample_count: 100000,
      duration_seconds: 52.1,
      model_version: null,
      calibration_version: null,
      window_count: null,
    });
    segmentSession.mockRejectedValue(
      new ApiError(412, "not_calibrated", "This participant has no completed calibration.", []),
    );

    renderPage();
    upload(new File(["Time\n"], "recording.csv", { type: "text/csv" }));
    await screen.findByText(/session s1/i);

    fireEvent.click(screen.getByRole("button", { name: /run segmentation/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/no completed calibration/i);
  });

  it("surfaces an upload failure without creating a session", async () => {
    signUpload.mockRejectedValue(
      new ApiError(401, "unauthenticated", "No signed-in user.", []),
    );

    renderPage();
    upload(new File(["Time\n"], "recording.csv", { type: "text/csv" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/no signed-in user/i);
    expect(createSession).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /run segmentation/i })).not.toBeInTheDocument();
  });
});
