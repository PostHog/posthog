import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { USER_PRESENCE_IDLE_MS, useUserPresence } from "./useUserPresence";

const MINUTE = 60 * 1000;

describe("useUserPresence", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Input only counts while the window has focus; jsdom has no real focus.
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts present", () => {
    const { result } = renderHook(() => useUserPresence());
    expect(result.current).toBe(true);
  });

  it("flips to away after the idle threshold with no input", () => {
    const { result } = renderHook(() => useUserPresence());

    act(() => {
      vi.advanceTimersByTime(USER_PRESENCE_IDLE_MS + MINUTE);
    });

    expect(result.current).toBe(false);
  });

  it("stays present while the user keeps interacting", () => {
    const { result } = renderHook(() => useUserPresence());

    act(() => {
      for (let i = 0; i < 15; i++) {
        vi.advanceTimersByTime(MINUTE);
        window.dispatchEvent(new Event("pointermove"));
      }
    });

    expect(result.current).toBe(true);
  });

  it("returns to present on interaction after going away", () => {
    const { result } = renderHook(() => useUserPresence());

    act(() => {
      vi.advanceTimersByTime(USER_PRESENCE_IDLE_MS + MINUTE);
    });
    expect(result.current).toBe(false);

    act(() => {
      window.dispatchEvent(new Event("keydown"));
    });

    expect(result.current).toBe(true);
  });

  it("ignores input while the window is unfocused", () => {
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    const { result } = renderHook(() => useUserPresence());

    act(() => {
      for (let i = 0; i < 11; i++) {
        vi.advanceTimersByTime(MINUTE);
        window.dispatchEvent(new Event("pointermove"));
      }
    });

    expect(result.current).toBe(false);
  });

  it("respects a custom idle threshold", () => {
    const { result } = renderHook(() => useUserPresence(2 * MINUTE));

    act(() => {
      vi.advanceTimersByTime(3 * MINUTE);
    });

    expect(result.current).toBe(false);
  });

  it("stays present under a sub-throttle idle threshold while interacting", () => {
    // idleMs below the 15s activity throttle: the throttle must scale down or
    // active input would be dropped and the user pinned "away".
    const { result } = renderHook(() => useUserPresence(10_000));

    act(() => {
      for (let i = 0; i < 20; i++) {
        vi.advanceTimersByTime(4_000);
        window.dispatchEvent(new Event("keydown"));
      }
    });

    expect(result.current).toBe(true);
  });

  it("removes listeners on unmount", () => {
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = renderHook(() => useUserPresence());

    unmount();

    const removed = removeSpy.mock.calls.map(([event]) => event);
    expect(removed).toEqual(
      expect.arrayContaining([
        "pointerdown",
        "pointermove",
        "keydown",
        "wheel",
        "focus",
      ]),
    );
  });
});
