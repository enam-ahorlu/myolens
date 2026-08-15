/**
 * The signed-in clinician, as React context.
 *
 * A thin wrapper over `onAuthStateChanged` (ADR-004): every screen that needs to know who is
 * signed in reads it from here rather than touching the Firebase SDK directly, so the SDK is
 * only ever initialised in one place (`lib/firebase.ts`) and mocked in one place in tests.
 */

import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  type User,
} from "firebase/auth";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { firebaseConfigured, getFirebaseAuth } from "./firebase";
import { useIdleTimeout } from "./idleTimeout";

interface AuthState {
  user: User | null;
  /** True until the first `onAuthStateChanged` callback fires -- distinguishes "still checking"
   * from "checked, and nobody is signed in", which a route guard must not confuse. */
  loading: boolean;
  configured: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const configured = firebaseConfigured();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(configured);

  useEffect(() => {
    if (!configured) return;
    const auth = getFirebaseAuth();
    return onAuthStateChanged(auth, (nextUser) => {
      setUser(nextUser);
      setLoading(false);
    });
  }, [configured]);

  // A5: sign out after 30 minutes with no mouse/keyboard/touch activity while someone is
  // signed in. Never armed for a signed-out visitor -- there is nothing to time out.
  useIdleTimeout(!!user, () => {
    void firebaseSignOut(getFirebaseAuth());
  });

  const value: AuthState = {
    user,
    loading,
    configured,
    signIn: async (email, password) => {
      await signInWithEmailAndPassword(getFirebaseAuth(), email, password);
    },
    signOut: async () => {
      await firebaseSignOut(getFirebaseAuth());
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth() must be called within an AuthProvider.");
  }
  return context;
}
