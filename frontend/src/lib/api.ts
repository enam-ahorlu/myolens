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

export const api = {
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

  // ---- Uploads, calibration, sessions -- request/requestBlob exported for the screens that
  // need the remaining frozen-surface routes not yet wired to a UI (see HANDOFF item 7).
  request,
  requestBlob,
};
