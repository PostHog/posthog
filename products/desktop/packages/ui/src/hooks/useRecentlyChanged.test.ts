import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRecentlyChanged } from "./useRecentlyChanged";

describe("useRecentlyChanged", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts settled, reports changes, and settles again once the value holds still", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useRecentlyChanged(value, 500),
      { initialProps: { value: "finished message" } },
    );
    expect(result.current).toBe(false);

    rerender({ value: "finished message plus" });
    expect(result.current).toBe(true);

    act(() => vi.advanceTimersByTime(400));
    rerender({ value: "finished message plus more" });
    act(() => vi.advanceTimersByTime(400));
    expect(result.current).toBe(true);

    act(() => vi.advanceTimersByTime(100));
    expect(result.current).toBe(false);
  });
});
