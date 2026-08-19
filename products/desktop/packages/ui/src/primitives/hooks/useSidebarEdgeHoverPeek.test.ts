import {
  PEEK_ABANDON_CLOSE_DELAY_MS,
  PEEK_CLOSE_MARGIN,
  PEEK_REVEAL_THRESHOLD,
  shouldCloseOnExit,
  shouldRevealOnEdge,
  useSidebarEdgeHoverPeek,
} from "@posthog/ui/primitives/hooks/useSidebarEdgeHoverPeek";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("shouldRevealOnEdge", () => {
  const threshold = PEEK_REVEAL_THRESHOLD;

  it.each([
    ["crosses into the zone from outside", 10, false, true],
    ["already inside the zone (no re-trigger)", 10, true, false],
    ["outside the zone", 100, false, false],
    ["flick from outside straight to the edge in one sample", 0, false, true],
    ["exactly on the threshold, crossing in", threshold, false, true],
    ["just past the threshold", threshold + 1, false, false],
  ])("%s", (_name, pointer, wasInside, expected) => {
    expect(shouldRevealOnEdge({ pointer, wasInside, threshold })).toBe(
      expected,
    );
  });
});

describe("shouldCloseOnExit", () => {
  const margin = PEEK_CLOSE_MARGIN;

  it.each([
    ["inside the panel", 100, 240, false],
    ["between the panel edge and the margin", 280, 240, false],
    ["exactly on the far edge (right edge)", 240, 240, false],
    ["exactly on the close boundary", 240 + margin, 240, false],
    ["past the close boundary into content", 240 + margin + 1, 240, true],
    ["stays open at the left edge / off-window", 0, 240, false],
    ["wide panel still open before its boundary", 400 + margin, 400, false],
    ["wide panel closes past its boundary", 400 + margin + 1, 400, true],
  ])("%s", (_name, pointer, width, expected) => {
    expect(shouldCloseOnExit({ pointer, width, margin })).toBe(expected);
  });
});

describe("useSidebarEdgeHoverPeek on window abandon", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // jsdom's document.hasFocus() is false by default; reveal requires focus.
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  const setup = (initialProps: { enabled: boolean; peeked: boolean }) => {
    const onReveal = vi.fn();
    const onClose = vi.fn();
    const { rerender, unmount } = renderHook(
      ({ enabled, peeked }: { enabled: boolean; peeked: boolean }) =>
        useSidebarEdgeHoverPeek({
          enabled,
          peeked,
          side: "left",
          width: 240,
          onReveal,
          onClose,
        }),
      { initialProps },
    );
    return { onReveal, onClose, rerender, unmount };
  };

  const blurWindow = () => window.dispatchEvent(new Event("blur"));
  const leaveDocument = () =>
    document.documentElement.dispatchEvent(new MouseEvent("mouseleave"));
  const moveTo = (clientX: number) =>
    document.dispatchEvent(new MouseEvent("mousemove", { clientX }));

  it.each([
    ["the window losing focus", blurWindow],
    ["the pointer leaving the document", leaveDocument],
  ])("closes an active peek on a timer after %s", (_name, abandon) => {
    const { onClose, unmount } = setup({ enabled: true, peeked: true });
    act(() => abandon());
    expect(onClose).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(PEEK_ABANDON_CLOSE_DELAY_MS));
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();
  });

  it.each([
    ["refocusing", blurWindow, () => window.dispatchEvent(new Event("focus"))],
    [
      "the pointer re-entering",
      leaveDocument,
      () => moveTo(PEEK_REVEAL_THRESHOLD - 1),
    ],
  ])("%s before the timer keeps the peek open", (_name, abandon, comeBack) => {
    const { onClose, unmount } = setup({ enabled: true, peeked: true });
    act(() => abandon());
    act(() => comeBack());
    act(() => vi.runAllTimers());
    expect(onClose).not.toHaveBeenCalled();
    unmount();
  });

  it.each([
    ["not peeked", { enabled: true, peeked: false }],
    ["disabled (open or resizing)", { enabled: false, peeked: true }],
  ])("does not close when %s", (_name, props) => {
    const { onClose, unmount } = setup(props);
    act(() => blurWindow());
    act(() => leaveDocument());
    act(() => vi.runAllTimers());
    expect(onClose).not.toHaveBeenCalled();
    unmount();
  });

  it("does not reveal on edge hover while the window is unfocused", () => {
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    const { onReveal, unmount } = setup({ enabled: true, peeked: false });
    act(() => moveTo(PEEK_REVEAL_THRESHOLD - 1));
    act(() => vi.runAllTimers());
    expect(onReveal).not.toHaveBeenCalled();
    unmount();
  });

  it("re-reveals on edge re-entry after the pointer left the document", () => {
    const { onReveal, onClose, rerender, unmount } = setup({
      enabled: true,
      peeked: false,
    });
    act(() => moveTo(PEEK_REVEAL_THRESHOLD - 1));
    expect(onReveal).toHaveBeenCalledTimes(1);

    rerender({ enabled: true, peeked: true });
    act(() => leaveDocument());
    act(() => vi.advanceTimersByTime(PEEK_ABANDON_CLOSE_DELAY_MS));
    expect(onClose).toHaveBeenCalledTimes(1);

    // Without the wasInside reset the pointer still counts as inside the edge
    // zone, and coming back through it would not reopen the peek.
    rerender({ enabled: true, peeked: false });
    act(() => moveTo(PEEK_REVEAL_THRESHOLD - 1));
    expect(onReveal).toHaveBeenCalledTimes(2);
    unmount();
  });
});
