import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNow } from "./useNow";

const MINUTE = 60 * 1000;

describe("useNow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("re-renders with the moved clock once a minute", () => {
    const { result } = renderHook(() => useNow());
    const first = result.current;

    act(() => {
      vi.advanceTimersByTime(MINUTE);
    });

    expect(result.current).toBeGreaterThanOrEqual(first + MINUTE);
  });

  it("shares one timer across subscribers and stops it when the last leaves", () => {
    const a = renderHook(() => useNow());
    const b = renderHook(() => useNow());
    expect(vi.getTimerCount()).toBe(1);

    a.unmount();
    expect(vi.getTimerCount()).toBe(1);

    b.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
