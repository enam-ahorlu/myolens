/**
 * Firestore security rules (H3, A3, SRS §5.1): "a test proves it."
 *
 * Runs against the real Firestore emulator (not a mock), loading the same firestore.rules the
 * project deploys. Every assertion here is about what the *client* SDK can and cannot do --
 * the Cloud Run service writes through the Admin SDK and bypasses these rules entirely by
 * design (TD-08), which is exactly why the audit log is "client-immutable," a claim this file
 * makes true rather than merely documented.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from "@firebase/rules-unit-testing";
import { deleteDoc, doc, getDoc, setDoc, updateDoc } from "firebase/firestore";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RULES_PATH = path.join(__dirname, "..", "firestore.rules");

let testEnv;

beforeAll(async () => {
  testEnv = await initializeTestEnvironment({
    projectId: "myolens-rules-test",
    firestore: {
      rules: readFileSync(RULES_PATH, "utf8"),
      host: "127.0.0.1",
      port: 8080,
    },
  });
});

afterAll(async () => {
  await testEnv.cleanup();
});

beforeEach(async () => {
  await testEnv.clearFirestore();
});

/** Seeds a document bypassing rules entirely -- the same trust level the Admin SDK has in
 * production, used here only to set up fixtures, never to assert anything about rules. */
async function seed(fn) {
  await testEnv.withSecurityRulesDisabled(fn);
}

describe("participants (A3: a clinician reads only their own)", () => {
  beforeEach(async () => {
    await seed(async (context) => {
      const db = context.firestore();
      await setDoc(doc(db, "participants", "p1"), { id: "p1", createdBy: "clinician-a" });
    });
  });

  it("denies an unauthenticated read", async () => {
    const db = testEnv.unauthenticatedContext().firestore();
    await assertFails(getDoc(doc(db, "participants", "p1")));
  });

  it("allows the owning clinician to read their own participant", async () => {
    const db = testEnv.authenticatedContext("clinician-a").firestore();
    await assertSucceeds(getDoc(doc(db, "participants", "p1")));
  });

  it("denies a different clinician reading someone else's participant", async () => {
    const db = testEnv.authenticatedContext("clinician-b").firestore();
    await assertFails(getDoc(doc(db, "participants", "p1")));
  });

  it("denies a client write, even from the owning clinician", async () => {
    const db = testEnv.authenticatedContext("clinician-a").firestore();
    await assertFails(setDoc(doc(db, "participants", "p2"), { createdBy: "clinician-a" }));
    await assertFails(
      updateDoc(doc(db, "participants", "p1"), { notes: "client-side edit attempt" }),
    );
    await assertFails(deleteDoc(doc(db, "participants", "p1")));
  });
});

describe("bouts (ownership follows the parent session, not a field of their own)", () => {
  beforeEach(async () => {
    await seed(async (context) => {
      const db = context.firestore();
      await setDoc(doc(db, "sessions", "s1"), { id: "s1", createdBy: "clinician-a" });
      await setDoc(doc(db, "bouts", "b1"), { id: "b1", sessionId: "s1", task: "WAK" });
    });
  });

  it("allows the session's owner to read a bout under it", async () => {
    const db = testEnv.authenticatedContext("clinician-a").firestore();
    await assertSucceeds(getDoc(doc(db, "bouts", "b1")));
  });

  it("denies a different clinician reading a bout under someone else's session", async () => {
    const db = testEnv.authenticatedContext("clinician-b").firestore();
    await assertFails(getDoc(doc(db, "bouts", "b1")));
  });
});

describe("the audit log (H3: client-immutable)", () => {
  beforeEach(async () => {
    await seed(async (context) => {
      const db = context.firestore();
      await setDoc(doc(db, "audit", "a1"), {
        actor: "clinician-a",
        action: "session.approve",
        targetType: "session",
        targetId: "s1",
      });
    });
  });

  it("denies a client update to an audit entry -- H3's literal requirement", async () => {
    const db = testEnv.authenticatedContext("clinician-a").firestore();
    await assertFails(updateDoc(doc(db, "audit", "a1"), { action: "tampered" }));
  });

  it("denies a client delete of an audit entry -- H3's literal requirement", async () => {
    const db = testEnv.authenticatedContext("clinician-a").firestore();
    await assertFails(deleteDoc(doc(db, "audit", "a1")));
  });

  it("also denies a client create -- every audit entry in this system is written server-side", async () => {
    const db = testEnv.authenticatedContext("clinician-a").firestore();
    await assertFails(
      setDoc(doc(db, "audit", "a2"), { actor: "clinician-a", action: "forged" }),
    );
  });

  it("allows a signed-in clinician to read the audit trail", async () => {
    const db = testEnv.authenticatedContext("clinician-a").firestore();
    await assertSucceeds(getDoc(doc(db, "audit", "a1")));
  });

  it("denies an unauthenticated read of the audit trail", async () => {
    const db = testEnv.unauthenticatedContext().firestore();
    await assertFails(getDoc(doc(db, "audit", "a1")));
  });
});

describe("anything not named in the rules file", () => {
  it("is denied by the default-deny fallback", async () => {
    const db = testEnv.authenticatedContext("clinician-a").firestore();
    await assertFails(getDoc(doc(db, "some_future_collection", "x")));
  });
});
