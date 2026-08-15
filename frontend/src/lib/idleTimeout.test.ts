import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IDLE_TIMEOUT_MS, useIdleTimeout } from "./idleTimeout";

describe("useIdleTimeout (A5)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("fires after 30 minutes of no activity while active", () => {
    const onTimeout = vi.fn();
    renderHook(() => useIdleTimeout(true, onTimeout));

    act(() => {
      vi.advanceTimersByTime(IDLE_TIMEOUT_MS - 1);
    });
    expect(onTimeout).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });

  it("resets the clock on activity, so it never fires while the operator is present", () => {
    const onTimeout = vi.fn();
    renderHook(() => useIdleTimeout(true, onTimeout));

    act(() => {
      vi.advanceTimersByTime(IDLE_TIMEOUT_MS - 1000);
      window.dispatchEvent(new Event("mousemove"));
      vi.advanceTimersByTime(IDLE_TIMEOUT_MS - 1000);
    });
    expect(onTimeout).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });

  it("never fires while inactive (signed out)", () => {
    const onTimeout = vi.fn();
    renderHook(() => useIdleTimeout(false, onTimeout));

    act(() => {
      vi.advanceTimersByTime(IDLE_TIMEOUT_MS * 2);
    });
    expect(onTimeout).not.toHaveBeenCalled();
  });

  it("stops the timer once active goes false, so a delayed sign-out never re-fires", () => {
    const onTimeout = vi.fn();
    const { rerender } = renderHook(({ active }) => useIdleTimeout(active, onTimeout), {
      initialProps: { active: true },
    });

    rerender({ active: false });

    act(() => {
      vi.advanceTimersByTime(IDLE_TIMEOUT_MS * 2);
    });
    expect(onTimeout).not.toHaveBeenCalled();
  });
});
