import { afterEach, describe, expect, it, vi } from "vitest";
import { yieldToPaint } from "./yieldToPaint";

describe("yieldToPaint", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  function stubVisibility(state: DocumentVisibilityState): void {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue(state);
  }

  function stallFrames(): void {
    vi.spyOn(globalThis, "requestAnimationFrame").mockReturnValue(0);
  }

  it("resolves while the window is hidden and no frame ever arrives", async () => {
    stubVisibility("hidden");
    stallFrames();

    await expect(yieldToPaint()).resolves.toBeUndefined();
    expect(globalThis.requestAnimationFrame).not.toHaveBeenCalled();
  });

  it("resolves on a timeout when frames stall while the window reports visible", async () => {
    vi.useFakeTimers();
    stubVisibility("visible");
    stallFrames();

    const settled = vi.fn();
    const pending = yieldToPaint().then(settled);

    await vi.advanceTimersByTimeAsync(99);
    expect(settled).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    await pending;
    expect(settled).toHaveBeenCalled();
  });

  it("resolves on the second frame rather than waiting out the timeout", async () => {
    vi.useFakeTimers();
    stubVisibility("visible");
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      frames.push(cb);
      return frames.length;
    });

    const settled = vi.fn();
    const pending = yieldToPaint().then(settled);

    frames[0]?.(0);
    frames[1]?.(0);
    await vi.advanceTimersByTimeAsync(0);
    await pending;

    expect(settled).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
