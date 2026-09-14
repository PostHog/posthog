import { act, render, renderHook } from "@testing-library/react";
import { StrictMode, useLayoutEffect } from "react";
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

  it("reports the change in the commit that first renders the new value", () => {
    const committed: boolean[] = [];
    function Probe({ value }: { value: string }) {
      const changing = useRecentlyChanged(value, 500);
      useLayoutEffect(() => {
        committed.push(changing);
      });
      return null;
    }

    const { rerender } = render(<Probe value="finished message" />);
    rerender(<Probe value="finished message plus" />);

    expect(committed).toEqual([false, true]);
  });

  it("stays settled on mount under StrictMode", () => {
    const committed: boolean[] = [];
    function Probe({ value }: { value: string }) {
      const changing = useRecentlyChanged(value, 500);
      useLayoutEffect(() => {
        committed.push(changing);
      });
      return null;
    }

    render(
      <StrictMode>
        <Probe value="finished message" />
      </StrictMode>,
    );
    act(() => vi.advanceTimersByTime(500));

    expect(committed.some(Boolean)).toBe(false);
  });
});
