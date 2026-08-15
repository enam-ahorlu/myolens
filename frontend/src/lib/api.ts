/**
 * The typed HTTP client for the backend (§10's frozen API surface).
 *
 * Every call attaches the signed-in clinician's Firebase ID token as a bearer credential
 * (ADR-004) and parses the backend's one error shape (`app.errors.ErrorEnvelope`) into a typed
 * `ApiError` on failure, so a component can switch on `error.code` the same way the SRS's error
 * table does, rather than re-parsing a response body at every call site.
 */

import { getFirebaseAuth } from "./firebase";

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Array<Record<string, unknown>>;

  constructor(status: number, code: string, message: string, details: Array<Record<string, unknown>>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface ErrorEnvelope {
  code: string;
  message: string;
  details?: Array<Record<string, unknown>>;
}

async function authHeader(): Promise<Record<string, string>> {
  const user = getFirebaseAuth().currentUser;
  if (!user) {
    // Every route requires authentication (I2); a call made with no signed-in user is a bug in
    // the caller, not something the backend should have to explain with a 401 round trip.
    throw new ApiError(401, "unauthenticated", "No signed-in user.", []);
  }
  const token = await user.getIdToken();
  return { Authorization: `Bearer ${token}` };
}

async function request<T>(
  path: string,
  init: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  const { auth = true, headers, ...rest } = init;
  const authHeaders = auth ? await authHeader() : {};

  const response = await fetch(`${BASE_URL}${path}`, {
    ...rest,
    headers: {
      ...(rest.body ? { "Content-Type": "application/json" } : {}),
      ...authHeaders,
      ...headers,
    },
  });

  if (!response.ok) {
    let envelope: ErrorEnvelope | null = null;
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      // A non-JSON error body (a proxy timeout page, for instance) still needs to surface as
      // *something* rather than an unhandled JSON-parse exception.
    }
    throw new ApiError(
      response.status,
      envelope?.code ?? "unknown",
      envelope?.message ?? `Request failed with status ${response.status}.`,
      envelope?.details ?? [],
    );
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    // The PDF export (G1) is the one route that returns a binary body -- callers that expect
    // that use `requestBlob` below instead of this generic JSON path.
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function requestBlob(path: string): Promise<Blob> {
  const authHeaders = await authHeader();
  const response = await fetch(`${BASE_URL}${path}`, { headers: authHeaders });
  if (!response.ok) {
    let envelope: ErrorEnvelope | null = null;
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      // see request()
    }
    throw new ApiError(
      response.status,
      envelope?.code ?? "unknown",
      envelope?.message ?? `Request failed with status ${response.status}.`,
      envelope?.details ?? [],
    );
  }
  return response.blob();
}

// ---- Participants (B1/B2, A3) ----------------------------------------------------------------

export type AgeBand = "under_18" | "18_29" | "30_44" | "45_59" | "60_74" | "75_plus";
export type Sex = "female" | "male" | "other" | "undisclosed";
export type AffectedSide = "left" | "right" | "bilateral" | "none";

export interface Participant {
  id: string;
  code: string;
  age_band: AgeBand;
  sex: Sex;
  affected_side: AffectedSide;
  notes: string;
  created_by: string;
  difficulty_band: string | null;
}

export interface ParticipantInput {
  code: string;
  age_band: AgeBand;
  sex: Sex;
  affected_side: AffectedSide;
  notes?: string;
}

// ---- Uploads, calibration -----------------------------------------------------------------

export type UploadKind = "calibration" | "session";

export interface SignUploadResponse {
  object_name: string;
  upload_url: string;
  method: string;
  expires_in_seconds: number;
}

export interface TaskCalibrationOut {
  window_count: number;
  block_count: number;
  status: string;
  sufficient: boolean;
}

export interface CalibrationOut {
  id: string;
  participant_id: string;
  version: number;
  created_at: string;
  per_task: Record<string, TaskCalibrationOut>;
  envelope_peak: number[];
  mahalanobis: number;
  difficulty_band: string;
  ood_flag: boolean;
  active: boolean;
}

// ---- Sessions, segmentation (D1-D8) --------------------------------------------------------

export type SessionStatus = "uploaded" | "segmented" | "approved";

export interface SessionOut {
  id: string;
  participant_id: string;
  status: SessionStatus;
  sample_count: number;
  duration_seconds: number;
  model_version: string | null;
  calibration_version: number | null;
  window_count: number | null;
}

export interface BoutOut {
  id: string;
  task: string;
  start_ms: number;
  end_ms: number;
  window_count: number;
  mean_confidence: number;
  flagged: boolean;
  flag_reasons: string[];
  excluded: boolean;
  exclusion_reason: string | null;
  corrected: boolean;
  original_task: string | null;
}

export interface SegmentationOut {
  session: SessionOut;
  bouts: BoutOut[];
  flagged_count: number;
}

// ---- Segmentation review (E3-E8) -----------------------------------------------------------

export type ExclusionReason = "artefact" | "transition" | "unobserved";

export type BoutCorrection =
  | { op: "relabel"; task: string }
  | { op: "split"; at_window: number }
  | { op: "merge"; neighbor_bout_id: string }
  | { op: "exclude"; reason: ExclusionReason };

export interface BoutCorrectionOut {
  bouts: BoutOut[];
  removed_bout_ids: string[];
}

// ---- Results: metrics (F1), export (G1) ----------------------------------------------------

export interface CoContractionOut {
  value: number | null;
  windows_used: number;
  windows_total: number;
}

export interface TaskMetricsOut {
  task: string;
  bout_count: number;
  bout_duration_total_s: number;
  //: 9 values, %CAL, in montage channel order -- null where the calibration channel it would be
  // divided by produced no usable signal.
  amp_mean: Array<number | null>;
  amp_peak: Array<number | null>;
  duty_cycle: number[];
  cci_knee: CoContractionOut;
  cci_ankle: CoContractionOut;
  model_confidence_mean: number;
  correction_rate_pct: number;
}

export interface SessionMetricsOut {
  session_id: string;
  channels: string[];
  flagged_count: number;
  tasks: TaskMetricsOut[];
}

// ---- Model card (H1) --------------------------------------------------------------------

export type PredictorMode = "ensemble" | "svm_only";

export interface AccuracyRegime {
  predictor: PredictorMode;
  label: string;
  macro_f1: number;
  balanced_acc: number;
  n_windows: number;
}

export interface HeldOutValidation {
  holdout_subjects: number[];
  training_subjects_n: number;
  n_windows: number;
  seed: number;
}

export interface TrainingProtocol {
  created_utc: string;
  window_ms: number;
  step_ms: number;
  bandpass_hz: number[];
  bandpass_order: number;
  envelope_ms: number;
  normalisation_mode: string;
}

export interface ModelCard {
  active_predictor: PredictorMode;
  active_version: string;
  active_sha256: string;
  accuracy_regimes: AccuracyRegime[];
  held_out_validation: HeldOutValidation;
  training_protocol: TrainingProtocol;
  classes: string[];
  montage_channels: string[];
  montage_contract_version: string;
  failure_modes: string[];
  intended_use: string;
}

// ---- Administration (A4) ---------------------------------------------------------------------

export type Role = "clinician" | "admin";

export interface Clinician {
  uid: string;
  email: string | null;
  role: Role;
  disabled: boolean;
}

export const api = {
  // Unauthenticated (see backend/app/routers/models.py) -- reachable from the footer before
  // sign-in, the same as the route itself.
  getModelCard: () => request<ModelCard>("/v1/models/current", { auth: false }),

  listParticipants: () => request<Participant[]>("/v1/participants"),

  getParticipant: (id: string) => request<Participant>(`/v1/participants/${id}`),

  createParticipant: (body: ParticipantInput) =>
    request<Participant>("/v1/participants", { method: "POST", body: JSON.stringify(body) }),

  editParticipant: (id: string, body: Partial<ParticipantInput>) =>
    request<Participant>(`/v1/participants/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteParticipant: (id: string) =>
    request<void>(`/v1/participants/${id}`, { method: "DELETE" }),

  // ---- Uploads (ADR-002) ------------------------------------------------------------------

  signUpload: (kind: UploadKind, participantId: string, contentType = "text/csv") =>
    request<SignUploadResponse>("/v1/uploads/sign", {
      method: "POST",
      body: JSON.stringify({ kind, participant_id: participantId, content_type: contentType }),
    }),

  // The signed URL is a direct-to-bucket PUT, not a backend route -- it carries no auth header
  // of ours (the signature itself is the credential) and the bucket's response body is not
  // JSON, so this bypasses `request()` entirely rather than forcing it through a shape it
  // wasn't built for.
  putToSignedUrl: async (uploadUrl: string, contentType: string, file: File | Blob) => {
    const response = await fetch(uploadUrl, {
      method: "PUT",
      headers: { "Content-Type": contentType },
      body: file,
    });
    if (!response.ok) {
      throw new ApiError(
        response.status,
        "upload_failed",
        `The upload to storage failed (status ${response.status}).`,
        [],
      );
    }
  },

  // ---- Calibration (C1-C5) ------------------------------------------------------------------

  createCalibration: (participantId: string, objectName: string) =>
    request<CalibrationOut>("/v1/calibrations", {
      method: "POST",
      body: JSON.stringify({ participant_id: participantId, object_name: objectName }),
    }),

  getActiveCalibration: (participantId: string) =>
    request<CalibrationOut>(`/v1/participants/${participantId}/calibration/active`),

  // ---- Sessions, segmentation (D1-D8) -------------------------------------------------------

  createSession: (participantId: string, objectName: string) =>
    request<SessionOut>("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ participant_id: participantId, object_name: objectName }),
    }),

  segmentSession: (sessionId: string) =>
    request<SegmentationOut>(`/v1/sessions/${sessionId}/segment`, { method: "POST" }),

  // ---- Segmentation review, approval (E3-E8) ------------------------------------------------

  correctBout: (sessionId: string, boutId: string, correction: BoutCorrection) =>
    request<BoutCorrectionOut>(`/v1/sessions/${sessionId}/bouts/${boutId}`, {
      method: "PATCH",
      body: JSON.stringify(correction),
    }),

  approveSession: (sessionId: string) =>
    request<SessionOut>(`/v1/sessions/${sessionId}/approve`, { method: "POST" }),

  // ---- Results: metrics (F1), export (G1) ---------------------------------------------------

  getSessionMetrics: (sessionId: string) =>
    request<SessionMetricsOut>(`/v1/sessions/${sessionId}/metrics`),

  exportSession: (sessionId: string) => requestBlob(`/v1/sessions/${sessionId}/export`),

  // ---- Administration (A4) -------------------------------------------------------------------

  listClinicians: () => request<Clinician[]>("/v1/admin/clinicians"),

  setClinicianRole: (uid: string, role: Role) =>
    request<Clinician>(`/v1/admin/clinicians/${uid}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),

  // request/requestBlob exported directly in case a future screen needs a frozen-surface route
  // not yet wrapped above.
  request,
  requestBlob,
};
