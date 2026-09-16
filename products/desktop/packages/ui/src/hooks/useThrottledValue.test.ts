import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useThrottledValue } from "./useThrottledValue";

describe("useThrottledValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("collapses a burst into the last value and lands it when the interval ends", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useThrottledValue(value, 100),
      { initialProps: { value: "a" } },
    );
    expect(result.current).toBe("a");

    act(() => vi.advanceTimersByTime(10));
    rerender({ value: "ab" });
    rerender({ value: "abc" });
    expect(result.current).toBe("a");

    act(() => vi.advanceTimersByTime(100));
    expect(result.current).toBe("abc");
  });

  it("passes the live value through while disabled and until the next emission after re-enabling", () => {
    const { result, rerender } = renderHook(
      ({ value, enabled }) => useThrottledValue(value, 100, enabled),
      { initialProps: { value: "a", enabled: true } },
    );

    act(() => vi.advanceTimersByTime(10));
    rerender({ value: "ab", enabled: false });
    expect(result.current).toBe("ab");

    rerender({ value: "abc", enabled: true });
    expect(result.current).toBe("abc");
    rerender({ value: "abcd", enabled: true });
    expect(result.current).toBe("abcd");

    act(() => vi.advanceTimersByTime(100));
    expect(result.current).toBe("abcd");
  });
});
