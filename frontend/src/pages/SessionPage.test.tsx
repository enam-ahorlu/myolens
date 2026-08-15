import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { SessionPage } from "./SessionPage";

const signUpload = vi.fn();
const putToSignedUrl = vi.fn();
const createSession = vi.fn();
const segmentSession = vi.fn();
const correctBout = vi.fn();
const approveSession = vi.fn();
const getSessionMetrics = vi.fn();
const exportSession = vi.fn();

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      contentTypeFor: (fileName: string) =>
        /\.gz$/i.test(fileName) ? "application/gzip" : "text/csv",
      signUpload: (kind: string, id: string, contentType: string) =>
        signUpload(kind, id, contentType),
      putToSignedUrl: (url: string, contentType: string, file: unknown) =>
        putToSignedUrl(url, contentType, file),
      createSession: (id: string, objectName: string) => createSession(id, objectName),
      segmentSession: (sessionId: string) => segmentSession(sessionId),
      correctBout: (sessionId: string, boutId: string, body: unknown) =>
        correctBout(sessionId, boutId, body),
      approveSession: (sessionId: string) => approveSession(sessionId),
      getSessionMetrics: (sessionId: string) => getSessionMetrics(sessionId),
      exportSession: (sessionId: string) => exportSession(sessionId),
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

const TWO_BOUTS = {
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
};

async function getToReview() {
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
  segmentSession.mockResolvedValue(TWO_BOUTS);

  renderPage();
  upload(new File(["Time\n"], "recording.csv", { type: "text/csv" }));
  await screen.findByText(/session s1/i);
  fireEvent.click(screen.getByRole("button", { name: /run segmentation/i }));
  await screen.findByText(/2 bouts/i);
}

describe("SessionPage", () => {
  beforeEach(() => {
    signUpload.mockReset();
    putToSignedUrl.mockReset();
    createSession.mockReset();
    segmentSession.mockReset();
    correctBout.mockReset();
    approveSession.mockReset();
    getSessionMetrics.mockReset();
    // Default to an empty, resolved metrics response -- most tests don't care about Results and
    // would otherwise leave the ResultsSection's effect calling an unmocked function.
    getSessionMetrics.mockResolvedValue({
      session_id: "s1",
      channels: [],
      flagged_count: 0,
      tasks: [],
    });
    exportSession.mockReset();
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

  it("sorts bouts least-certain first (E2) and labels the ordering", async () => {
    await getToReview();

    // b2 (0.40 confidence) starts later than b1 (0.91 confidence) but must render first.
    const rows = screen.getAllByRole("row").filter((r) => r.getAttribute("aria-label"));
    expect(rows[0]).toHaveAttribute("aria-label", "Bout b2");
    expect(rows[1]).toHaveAttribute("aria-label", "Bout b1");
    expect(screen.getByRole("note")).toHaveTextContent(/sorted least-certain first/i);
  });

  it("renders the segmentation timeline once bouts exist (E1)", async () => {
    await getToReview();
    expect(screen.getByRole("list", { name: /segmentation timeline/i })).toBeInTheDocument();
  });

  it("relabels a bout and reflects the correction", async () => {
    await getToReview();

    correctBout.mockResolvedValue({
      bouts: [{ ...TWO_BOUTS.bouts[1], task: "UPS", corrected: true, original_task: "DNS" }],
      removed_bout_ids: [],
    });

    const row = screen.getByLabelText("Action for bout b2").closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /apply/i }));

    await waitFor(() =>
      expect(correctBout).toHaveBeenCalledWith("s1", "b2", { op: "relabel", task: "DNS" }),
    );
    expect(await screen.findByText(/\(corrected\)/i)).toBeInTheDocument();
  });

  it("excludes a bout and removes its review controls", async () => {
    await getToReview();

    correctBout.mockResolvedValue({
      bouts: [{ ...TWO_BOUTS.bouts[1], excluded: true, exclusion_reason: "artefact" }],
      removed_bout_ids: [],
    });

    const row = screen.getByLabelText("Action for bout b2").closest("tr") as HTMLElement;
    fireEvent.change(within(row).getByRole("combobox", { name: /action for bout/i }), {
      target: { value: "exclude" },
    });
    fireEvent.click(within(row).getByRole("button", { name: /apply/i }));

    await waitFor(() =>
      expect(correctBout).toHaveBeenCalledWith("s1", "b2", {
        op: "exclude",
        reason: "artefact",
      }),
    );
    expect(await screen.findByText("artefact")).toBeInTheDocument();
  });

  it("surfaces a rejected relabel (uncalibrated task) without losing the bout", async () => {
    await getToReview();

    correctBout.mockRejectedValue(
      new ApiError(
        422,
        "validation_failed",
        "'STDUP' is not a task this participant is calibrated for",
        [],
      ),
    );

    const row = screen.getByLabelText("Action for bout b1").closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /apply/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/not a task this participant/i);
    expect(screen.getByText(/2 bouts/i)).toBeInTheDocument();
  });

  it("approves the segmentation and locks further corrections", async () => {
    await getToReview();

    approveSession.mockResolvedValue({ ...TWO_BOUTS.session, status: "approved" });

    fireEvent.click(screen.getByRole("button", { name: /approve segmentation/i }));

    await waitFor(() => expect(approveSession).toHaveBeenCalledWith("s1"));
    expect(await screen.findByText(/approved segmentation/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Action for bout b1")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /approve segmentation/i }),
    ).not.toBeInTheDocument();
  });

  it("loads and shows the §3.3 metrics once approved", async () => {
    await getToReview();
    approveSession.mockResolvedValue({ ...TWO_BOUTS.session, status: "approved" });
    getSessionMetrics.mockResolvedValue({
      session_id: "s1",
      channels: ["ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7", "ch8", "ch9"],
      flagged_count: 1,
      tasks: [
        {
          task: "WAK",
          bout_count: 1,
          bout_duration_total_s: 2.0,
          amp_mean: [10, 12, null, 8, 9, 11, 7, 6, 5],
          amp_peak: [20, 22, null, 18, 19, 21, 17, 16, 15],
          duty_cycle: [30, 32, 0, 28, 29, 31, 27, 26, 25],
          cci_knee: { value: 0.42, windows_used: 6, windows_total: 8 },
          cci_ankle: { value: null, windows_used: 0, windows_total: 8 },
          model_confidence_mean: 0.91,
          correction_rate_pct: 0,
        },
      ],
    });

    fireEvent.click(screen.getByRole("button", { name: /approve segmentation/i }));
    await waitFor(() => expect(approveSession).toHaveBeenCalled());

    expect(await screen.findByText(/0.42 \(6\/8 windows\)/)).toBeInTheDocument();
    expect(screen.getByText(/— \(0\/8 windows\)/)).toBeInTheDocument();
  });

  it("downloads the PDF export via a blob URL", async () => {
    await getToReview();
    approveSession.mockResolvedValue({ ...TWO_BOUTS.session, status: "approved" });
    getSessionMetrics.mockResolvedValue({
      session_id: "s1",
      channels: [],
      flagged_count: 0,
      tasks: [],
    });
    const blob = new Blob(["%PDF-fake"], { type: "application/pdf" });
    exportSession.mockResolvedValue(blob);

    const createObjectURL = vi.fn().mockReturnValue("blob:fake");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    fireEvent.click(screen.getByRole("button", { name: /approve segmentation/i }));
    await waitFor(() => expect(approveSession).toHaveBeenCalled());
    await screen.findByText(/no task had any non-excluded bout/i);

    fireEvent.click(screen.getByRole("button", { name: /download pdf report/i }));

    await waitFor(() => expect(exportSession).toHaveBeenCalledWith("s1"));
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");
    vi.unstubAllGlobals();
  });
});
