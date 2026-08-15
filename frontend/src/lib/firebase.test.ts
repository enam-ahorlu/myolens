import { afterEach, describe, expect, it, vi } from "vitest";

describe("firebaseConfigured", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("is false when any VITE_FIREBASE_* value is missing", async () => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "myolens.firebaseapp.com");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "myolens");
    vi.stubEnv("VITE_FIREBASE_APP_ID", "1:123:web:abc");
    const { firebaseConfigured } = await import("./firebase");
    expect(firebaseConfigured()).toBe(false);
  });

  it("is true once every value is supplied", async () => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "AIza-fake");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "myolens.firebaseapp.com");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "myolens");
    vi.stubEnv("VITE_FIREBASE_APP_ID", "1:123:web:abc");
    const { firebaseConfigured } = await import("./firebase");
    expect(firebaseConfigured()).toBe(true);
  });

  it("getFirebaseAuth refuses with an actionable message when unconfigured", async () => {
    vi.stubEnv("VITE_FIREBASE_API_KEY", "");
    vi.stubEnv("VITE_FIREBASE_AUTH_DOMAIN", "");
    vi.stubEnv("VITE_FIREBASE_PROJECT_ID", "");
    vi.stubEnv("VITE_FIREBASE_APP_ID", "");
    const { getFirebaseAuth } = await import("./firebase");
    expect(() => getFirebaseAuth()).toThrow(/\.env\.local/);
  });
});
