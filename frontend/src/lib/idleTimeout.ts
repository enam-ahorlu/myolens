/**
 * A5: 30-minute idle timeout (SRS §4.2 A5, "Should" -- may be manual/documented, but a real
 * timeout is cheaper and more defensible than a documentation-only answer for a clinical tool
 * left signed in on a shared workstation).
 *
 * Kept independent of the Firebase auth wiring in `auth.tsx` and of React so it can be unit
 * tested with fake timers against a bare callback, rather than through `onAuthStateChanged`.
 */

import { useEffect, useRef } from "react";

export const IDLE_TIMEOUT_MS = 30 * 60 * 1000;

/** DOM events that count as "the operator is here." Deliberately broad: a clinician reading a
 * long recording without touching the mouse for a while is a false positive this list is meant
 * to avoid, but reading in this product always involves scrolling or clicking through bouts. */
const ACTIVITY_EVENTS: readonly (keyof WindowEventMap)[] = [
  "mousedown",
  "mousemove",
  "keydown",
  "scroll",
  "touchstart",
  "click",
];

/**
 * Calls `onTimeout` once, after `timeoutMs` of no activity event on `window`, but only while
 * `active` is true. Resets on every qualifying event. `active` transitioning to false clears any
 * pending timer, so signing out never fires a *second* time against an already-signed-out user.
 */
export function useIdleTimeout(active: boolean, onTimeout: () => void, timeoutMs: number = IDLE_TIMEOUT_MS): void {
  const onTimeoutRef = useRef(onTimeout);
  onTimeoutRef.current = onTimeout;

  useEffect(() => {
    if (!active) return;

    let timer: ReturnType<typeof setTimeout>;
    function reset() {
      clearTimeout(timer);
      timer = setTimeout(() => onTimeoutRef.current(), timeoutMs);
    }

    reset();
    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, reset, { passive: true });
    }

    return () => {
      clearTimeout(timer);
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, reset);
      }
    };
  }, [active, timeoutMs]);
}
