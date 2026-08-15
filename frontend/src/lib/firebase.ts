/**
 * Firebase Web SDK bootstrap (ADR-004).
 *
 * The backend verifies a Firebase ID token on every route; this is the one place that token
 * comes from. Initialisation is lazy (`getFirebaseAuth()`, not a module-level side effect) so
 * importing this module in a test never reaches out to Firebase unless a test actually calls it.
 */

import { initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

let app: FirebaseApp | undefined;
let auth: Auth | undefined;

/**
 * True once every `VITE_FIREBASE_*` value in `.env.example` has been supplied. A missing value
 * is a deployment-configuration problem, not a code bug -- the login screen checks this and
 * shows a specific, actionable message instead of letting the Firebase SDK throw a generic
 * "invalid API key" deep inside a click handler.
 */
export function firebaseConfigured(): boolean {
  const env = import.meta.env;
  return Boolean(
    env.VITE_FIREBASE_API_KEY &&
      env.VITE_FIREBASE_AUTH_DOMAIN &&
      env.VITE_FIREBASE_PROJECT_ID &&
      env.VITE_FIREBASE_APP_ID,
  );
}

export function getFirebaseAuth(): Auth {
  if (!firebaseConfigured()) {
    throw new Error(
      "Firebase is not configured. Copy .env.example to .env.local and fill in the " +
        "VITE_FIREBASE_* values from the Firebase console (Project settings > General > " +
        "Your apps > Web app).",
    );
  }
  if (!app) {
    const env = import.meta.env;
    app = initializeApp({
      apiKey: env.VITE_FIREBASE_API_KEY,
      authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
      projectId: env.VITE_FIREBASE_PROJECT_ID,
      appId: env.VITE_FIREBASE_APP_ID,
    });
  }
  if (!auth) {
    auth = getAuth(app);
  }
  return auth;
}
