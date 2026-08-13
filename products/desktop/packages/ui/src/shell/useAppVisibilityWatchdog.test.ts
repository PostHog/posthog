import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({
  captureException: vi.fn(),
}));

vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({
      error: vi.fn(),
      warn: vi.fn(),
      info: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

import { captureException } from "@posthog/ui/shell/analytics";
import { useAppVisibilityWatchdog } from "./useAppVisibilityWatchdog";

function mountElement(opacity: string, width: number, height: number) {
  const element = document.createElement("div");
  element.style.opacity = opacity;
  element.getBoundingClientRect = () => ({ width, height }) as DOMRect;
  document.body.append(element);
  return element;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.mocked(captureException).mockClear();
  document.body.innerHTML = "";
});

describe("useAppVisibilityWatchdog", () => {
  it.each([
    {
      name: "invisible via opacity",
      opacity: "0",
      width: 1200,
      height: 800,
      active: true,
      reports: true,
    },
    {
      name: "collapsed to zero size",
      opacity: "1",
      width: 0,
      height: 0,
      active: true,
      reports: true,
    },
    {
      name: "visible",
      opacity: "1",
      width: 1200,
      height: 800,
      active: true,
      reports: false,
    },
    {
      name: "inactive",
      opacity: "0",
      width: 1200,
      height: 800,
      active: false,
      reports: false,
    },
  ])(
    "reports=$reports when $name",
    ({ opacity, width, height, active, reports }) => {
      const ref = { current: mountElement(opacity, width, height) };
      renderHook(() => useAppVisibilityWatchdog(ref, active));

      vi.advanceTimersByTime(3000);

      expect(captureException).toHaveBeenCalledTimes(reports ? 1 : 0);
    },
  );

  it("reports the element's opacity and source", () => {
    const ref = { current: mountElement("0", 1200, 800) };
    renderHook(() => useAppVisibilityWatchdog(ref, true));

    vi.advanceTimersByTime(3000);

    expect(captureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        source: "app-visibility-watchdog",
        opacity: 0,
      }),
    );
  });

  it("does not report after unmounting before the deadline", () => {
    const ref = { current: mountElement("0", 1200, 800) };
    const { unmount } = renderHook(() => useAppVisibilityWatchdog(ref, true));

    unmount();
    vi.advanceTimersByTime(3000);

    expect(captureException).not.toHaveBeenCalled();
  });

  it("arms when active flips from false to true", () => {
    const ref = { current: mountElement("0", 1200, 800) };
    const { rerender } = renderHook(
      ({ active }) => useAppVisibilityWatchdog(ref, active),
      { initialProps: { active: false } },
    );

    vi.advanceTimersByTime(3000);
    expect(captureException).not.toHaveBeenCalled();

    rerender({ active: true });
    vi.advanceTimersByTime(3000);
    expect(captureException).toHaveBeenCalledOnce();
  });

  it("does nothing when the ref never attaches", () => {
    const ref = { current: null };
    renderHook(() => useAppVisibilityWatchdog(ref, true));

    vi.advanceTimersByTime(3000);

    expect(captureException).not.toHaveBeenCalled();
  });
});
