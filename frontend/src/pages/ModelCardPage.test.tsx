import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ModelCard } from "../lib/api";
import { ModelCardPage } from "./ModelCardPage";

const getModelCard = vi.fn();

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      getModelCard: () => getModelCard(),
    },
  };
});

const CARD: ModelCard = {
  active_predictor: "ensemble",
  active_version: "ensemble-1.0.0",
  active_sha256: "a".repeat(64),
  loso_accuracy: [
    {
      regime: "transductive",
      label: "LOSO over 40 subjects, statistics from the whole recording. What this runs.",
      macro_f1: 0.858,
      n_subjects: 40,
      describes_this_system: true,
    },
    {
      regime: "causal",
      label: "Past samples only, as a streaming system would have to. Not this system.",
      macro_f1: 0.817,
      n_subjects: 40,
      describes_this_system: false,
    },
  ],
  accuracy_regimes: [
    {
      predictor: "svm_only",
      label: "SVM only (Freq-72) -- the fallback, not the default",
      macro_f1: 0.79,
      balanced_acc: 0.789,
      n_windows: 1983,
    },
    {
      predictor: "ensemble",
      label: "SVM + ResNet-SE+CD soft-vote ensemble -- the default",
      macro_f1: 0.876,
      balanced_acc: 0.877,
      n_windows: 1983,
    },
  ],
  held_out_validation: {
    holdout_subjects: [10, 13, 22],
    training_subjects_n: 37,
    n_windows: 1983,
    seed: 42,
  },
  training_protocol: {
    created_utc: "2026-08-13T04:49:25Z",
    window_ms: 250,
    step_ms: 125,
    bandpass_hz: [20, 450],
    bandpass_order: 4,
    envelope_ms: 50,
    normalisation_mode: "per_subject_zscore (transductive)",
  },
  classes: ["DNS", "STDUP", "UPS", "WAK"],
  montage_channels: ["sEMG: tensor fascia lata", "sEMG: rectus femoris"],
  montage_contract_version: "1.0.0",
  failure_modes: ["Stair descent (DNS) is the weakest of the four classes, at about 0.81 F1."],
  intended_use: "MyoLens is not a medical device.\n\nSecond paragraph.",
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/model-card"]}>
      <Routes>
        <Route path="/model-card" element={<ModelCardPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ModelCardPage", () => {
  beforeEach(() => {
    getModelCard.mockReset();
  });

  it("renders both accuracy regimes, labelled", async () => {
    getModelCard.mockResolvedValue(CARD);
    renderPage();

    expect(await screen.findByText(/SVM only \(Freq-72\)/)).toBeInTheDocument();
    expect(screen.getByText(/SVM \+ ResNet-SE\+CD soft-vote ensemble/)).toBeInTheDocument();
    expect(screen.getByText("0.790")).toBeInTheDocument();
    expect(screen.getByText("0.876")).toBeInTheDocument();
  });

  it("renders the active model's version and SHA-256", async () => {
    getModelCard.mockResolvedValue(CARD);
    renderPage();

    expect(await screen.findByText(/ensemble-1\.0\.0/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`SHA-256: ${"a".repeat(64)}`))).toBeInTheDocument();
  });

  it("renders held-out validation, montage, classes and failure modes", async () => {
    getModelCard.mockResolvedValue(CARD);
    renderPage();

    await screen.findByText(/37 training subjects/);
    expect(screen.getByText(/10, 13, 22/)).toBeInTheDocument();
    expect(screen.getByText("sEMG: tensor fascia lata")).toBeInTheDocument();
    expect(screen.getByText(/DNS, STDUP, UPS, WAK/)).toBeInTheDocument();
    expect(screen.getByText(/Stair descent \(DNS\)/)).toBeInTheDocument();
  });

  it("renders the intended-use statement", async () => {
    getModelCard.mockResolvedValue(CARD);
    renderPage();

    expect(await screen.findByText("MyoLens is not a medical device.")).toBeInTheDocument();
    expect(screen.getByText("Second paragraph.")).toBeInTheDocument();
  });

  it("shows an error if the model card fails to load", async () => {
    getModelCard.mockRejectedValue(new ApiError(500, "internal", "Something went wrong.", []));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
  });

  // FR-09/NFR-04 on the surface an examiner reads. The page used to head the held-out table
  // "Accuracy, both regimes" and caption it as satisfying FR-09 -- but those are two *predictor*
  // configurations measured on three subjects, not the two *normalisation* regimes FR-09 names,
  // and the number shown ran higher than the defensible one.
  it("leads with the leave-one-subject-out figures and marks the held-out check as indicative", async () => {
    getModelCard.mockResolvedValue(CARD);
    renderPage();
    expect(await screen.findByRole("heading", { name: /leave-one-subject-out/i })).toBeInTheDocument();
    expect(screen.getByText("0.858")).toBeInTheDocument();
    expect(screen.getByText("0.817")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /indicative only/i })).toBeInTheDocument();
  });
});
