import type { SketchpadPresenceInput } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePresenceSender } from "./usePresenceSender";

const { mutate } = vi.hoisted(() => ({
  mutate:
    vi.fn<
      (input: { id: string; presence: SketchpadPresenceInput }) => Promise<void>
    >(),
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({ sketchpadStream: { sendPresence: { mutate } } }),
}));

describe("usePresenceSender", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    mutate.mockReset().mockResolvedValue(undefined);
  });
  afterEach(() => vi.useRealTimers());

  it("keeps one request in flight and sends only the latest pending position", async () => {
    let finish!: () => void;
    mutate.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const { result, unmount } = renderHook(() => usePresenceSender("board"), {
      wrapper: StrictMode,
    });
    act(() => result.current.reportCursor({ x: 1.2, y: 2.8 }));
    act(() => {
      for (let x = 2; x <= 1000; x++) result.current.reportCursor({ x, y: 0 });
      result.current.reportSelection(
        Array.from({ length: 100 }, (_, index) => `fragment-${index}`),
      );
    });
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0].presence.cursor).toEqual({ x: 1, y: 3 });

    await act(async () => {
      finish();
    });

    expect(mutate).toHaveBeenCalledTimes(2);
    expect(mutate.mock.calls[1][0].presence.cursor).toEqual({ x: 1000, y: 0 });
    expect(mutate.mock.calls[1][0].presence.selectedIds).toHaveLength(50);
    act(() => result.current.reportCursor(null));
    await act(() => vi.advanceTimersByTimeAsync(99));
    expect(mutate).toHaveBeenCalledTimes(2);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(mutate).toHaveBeenCalledTimes(3);
    expect(mutate.mock.calls[2][0].presence.cursor).toBeNull();
    act(() => result.current.reportSelection(["pending"]));
    unmount();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mutate).toHaveBeenCalledTimes(3);
  });

  it("skips unchanged presence and clears the cursor on blur", async () => {
    const { result, rerender, unmount } = renderHook(() =>
      usePresenceSender("board"),
    );
    act(() => {
      result.current.reportCursor({ x: 1.2, y: 2.8 });
      result.current.reportViewport({ x: 0, y: 0, zoom: 1 });
      result.current.reportSelection(["one"]);
      result.current.reportCaret({ key: "text", anchor: "a", focus: "b" });
    });
    await act(() => vi.advanceTimersByTimeAsync(100));
    const handle = result.current;
    rerender();
    expect(result.current).toBe(handle);
    act(() => {
      result.current.reportCursor({ x: 1.4, y: 3.1 });
      result.current.reportViewport({ x: 0, y: 0, zoom: 1 });
      result.current.reportSelection(["one"]);
      result.current.reportCaret({ key: "text", anchor: "a", focus: "b" });
    });
    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(mutate).toHaveBeenCalledTimes(2);
    act(() => window.dispatchEvent(new Event("blur")));
    expect(mutate.mock.lastCall?.[0].presence).toMatchObject({
      cursor: null,
      viewport: { x: 0, y: 0, zoom: 1 },
      selectedIds: ["one"],
      carets: [{ key: "text", anchor: "a", focus: "b" }],
    });
    unmount();
  });

  it("does not send old presence or resume an old request on another board", async () => {
    let fail!: (reason: Error) => void;
    mutate.mockReturnValueOnce(
      new Promise<void>((_resolve, reject) => {
        fail = reject;
      }),
    );
    const { result, rerender, unmount } = renderHook(
      ({ sketchpadId }) => usePresenceSender(sketchpadId),
      { initialProps: { sketchpadId: "first" } },
    );
    act(() => result.current.reportCursor({ x: 1, y: 2 }));
    act(() => result.current.reportSelection(["old"]));
    rerender({ sketchpadId: "second" });
    act(() => result.current.reportCursor({ x: 3, y: 4 }));
    await act(async () => {
      fail(new Error("Disconnected"));
    });
    await act(() => vi.advanceTimersByTimeAsync(1000));

    expect(mutate).toHaveBeenCalledTimes(2);
    expect(mutate.mock.calls[1][0]).toMatchObject({
      id: "second",
      presence: {
        cursor: { x: 3, y: 4 },
        selectedIds: [],
        viewport: null,
        carets: [],
      },
    });
    unmount();
  });
});
