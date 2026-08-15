import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { CalibrationPage } from "./CalibrationPage";

const getActiveCalibration = vi.fn();
const signUpload = vi.fn();
const putToSignedUrl = vi.fn();
const createCalibration = vi.fn();

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      getActiveCalibration: (id: string) => getActiveCalibration(id),
      signUpload: (kind: string, id: string, contentType: string) =>
        signUpload(kind, id, contentType),
      putToSignedUrl: (url: string, contentType: string, file: unknown) =>
        putToSignedUrl(url, contentType, file),
      createCalibration: (id: string, objectName: string) => createCalibration(id, objectName),
    },
  };
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/participants/p1/calibration"]}>
      <Routes>
        <Route path="/participants/:participantId/calibration" element={<CalibrationPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CalibrationPage", () => {
  beforeEach(() => {
    getActiveCalibration.mockReset();
    signUpload.mockReset();
    putToSignedUrl.mockReset();
    createCalibration.mockReset();
  });

  it("shows a no-calibration message for a brand-new participant (412 not_calibrated)", async () => {
    getActiveCalibration.mockRejectedValue(
      new ApiError(412, "not_calibrated", "This participant has no completed calibration.", []),
    );
    renderPage();
    expect(await screen.findByText(/no calibration on record yet/i)).toBeInTheDocument();
  });

  it("shows the active calibration's per-task sufficiency", async () => {
    getActiveCalibration.mockResolvedValue({
      id: "c1",
      participant_id: "p1",
      version: 2,
      created_at: "2026-08-15T00:00:00Z",
      per_task: {
        DNS: { window_count: 12, block_count: 3, status: "calibrated", sufficient: true },
        STDUP: { window_count: 0, block_count: 0, status: "insufficient", sufficient: false },
        UPS: { window_count: 10, block_count: 3, status: "calibrated", sufficient: true },
        WAK: { window_count: 15, block_count: 4, status: "calibrated", sufficient: true },
      },
      envelope_peak: [1, 1, 1, 1, 1, 1, 1, 1, 1],
      mahalanobis: 6.2,
      difficulty_band: "typical",
      ood_flag: false,
      active: true,
    });

    renderPage();

    expect(await screen.findByText(/version 2/i)).toBeInTheDocument();
    expect(screen.getByText(/typical difficulty/)).toBeInTheDocument();
    expect(screen.getByText("insufficient")).toBeInTheDocument();
  });

  it("flags an out-of-distribution active calibration rather than hiding it", async () => {
    getActiveCalibration.mockResolvedValue({
      id: "c1",
      participant_id: "p1",
      version: 1,
      created_at: "2026-08-15T00:00:00Z",
      per_task: {},
      envelope_peak: [0, 0, 0, 0, 0, 0, 0, 0, 0],
      mahalanobis: 20,
      difficulty_band: "hard",
      ood_flag: true,
      active: true,
    });

    renderPage();

    expect(await screen.findByRole("status")).toHaveTextContent(/flagged out-of-distribution/i);
  });

  it("uploads a file through sign, PUT, then register, and shows the result", async () => {
    getActiveCalibration.mockRejectedValue(
      new ApiError(412, "not_calibrated", "This participant has no completed calibration.", []),
    );
    signUpload.mockResolvedValue({
      object_name: "calibration/p1/abc.csv",
      upload_url: "https://storage.example/signed",
      method: "PUT",
      expires_in_seconds: 900,
    });
    putToSignedUrl.mockResolvedValue(undefined);
    createCalibration.mockResolvedValue({
      id: "c2",
      participant_id: "p1",
      version: 1,
      created_at: "2026-08-15T00:00:00Z",
      per_task: {},
      envelope_peak: [0, 0, 0, 0, 0, 0, 0, 0, 0],
      mahalanobis: 5,
      difficulty_band: "typical",
      ood_flag: false,
      active: true,
    });

    renderPage();
    await screen.findByText(/no calibration on record yet/i);

    const file = new File(["Time,label\n"], "capture.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText(/calibration csv/i), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(createCalibration).toHaveBeenCalledWith("p1", "calibration/p1/abc.csv"));
    expect(await screen.findByText(/calibration v1 registered/i)).toBeInTheDocument();
  });

  it("surfaces an out-of-distribution refusal without discarding the retained record", async () => {
    getActiveCalibration.mockRejectedValueOnce(
      new ApiError(412, "not_calibrated", "This participant has no completed calibration.", []),
    );
    signUpload.mockResolvedValue({
      object_name: "calibration/p1/abc.csv",
      upload_url: "https://storage.example/signed",
      method: "PUT",
      expires_in_seconds: 900,
    });
    putToSignedUrl.mockResolvedValue(undefined);
    createCalibration.mockRejectedValue(
      new ApiError(
        422,
        "out_of_distribution",
        "This participant's calibration lies outside the distribution the model was trained on.",
        [],
      ),
    );
    getActiveCalibration.mockResolvedValueOnce({
      id: "c3",
      participant_id: "p1",
      version: 1,
      created_at: "2026-08-15T00:00:00Z",
      per_task: {},
      envelope_peak: [0, 0, 0, 0, 0, 0, 0, 0, 0],
      mahalanobis: 20,
      difficulty_band: "hard",
      ood_flag: true,
      active: true,
    });

    renderPage();
    await screen.findByText(/no calibration on record yet/i);

    const file = new File(["Time,label\n"], "capture.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText(/calibration csv/i), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/outside the distribution/i);
    expect(await screen.findByRole("status")).toHaveTextContent(/flagged out-of-distribution/i);
  });
});
