import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockGetIdToken = vi.fn().mockResolvedValue("fake-id-token");
let mockCurrentUser: { getIdToken: typeof mockGetIdToken } | null = {
  getIdToken: mockGetIdToken,
};

vi.mock("./firebase", () => ({
  getFirebaseAuth: () => ({ get currentUser() { return mockCurrentUser; } }),
}));

describe("api client", () => {
  beforeEach(() => {
    mockCurrentUser = { getIdToken: mockGetIdToken };
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("attaches a bearer token from the signed-in user's ID token", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const { api } = await import("./api");

    await api.listParticipants();

    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer fake-id-token");
  });

  it("refuses to call the API with no signed-in user, rather than let the backend 401", async () => {
    mockCurrentUser = null;
    const { api, ApiError } = await import("./api");

    await expect(api.listParticipants()).rejects.toBeInstanceOf(ApiError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("parses the backend's error envelope into a typed ApiError", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "not_calibrated",
          message: "This participant has no completed calibration.",
          details: [{ participant_id: "p1" }],
        }),
        { status: 412, headers: { "content-type": "application/json" } },
      ),
    );
    const { api, ApiError } = await import("./api");

    let caught: unknown;
    try {
      await api.listParticipants();
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    const error = caught as InstanceType<typeof ApiError>;
    expect(error.status).toBe(412);
    expect(error.code).toBe("not_calibrated");
    expect(error.details).toEqual([{ participant_id: "p1" }]);
  });

  it("degrades to a generic message when the error body isn't JSON", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("<html>502 Bad Gateway</html>", { status: 502 }),
    );
    const { api } = await import("./api");

    await expect(api.listParticipants()).rejects.toMatchObject({
      status: 502,
      code: "unknown",
    });
  });
});
