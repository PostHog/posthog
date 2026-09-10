import { afterEach, describe, expect, it, vi } from "vitest";
import { createNavigationTiming } from "./navigationTiming";

describe("createNavigationTiming", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("records the duration after the destination has painted", () => {
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      frames.push(cb);
      return frames.length;
    });
    vi.spyOn(performance, "now")
      .mockReturnValueOnce(100)
      .mockReturnValueOnce(175);
    const timing = createNavigationTiming();
    const record = vi.fn();

    timing.start();
    timing.settle(record);
    frames[0]?.(0);

    expect(record).not.toHaveBeenCalled();

    frames[1]?.(0);

    expect(record).toHaveBeenCalledWith(75);
  });

  it.each([
    "settles before navigation starts",
    "is replaced by a newer navigation",
  ])("does not record when it %s", (caseName) => {
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      frames.push(cb);
      return frames.length;
    });
    const timing = createNavigationTiming();
    const record = vi.fn();

    if (caseName === "is replaced by a newer navigation") {
      timing.start();
    }
    timing.settle(record);
    timing.start();
    frames[0]?.(0);
    frames[1]?.(0);

    expect(record).not.toHaveBeenCalled();
  });

  it("does not record while the window is hidden", () => {
    let visibility: DocumentVisibilityState = "visible";
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(document, "visibilityState", "get").mockImplementation(
      () => visibility,
    );
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      frames.push(cb);
      return frames.length;
    });
    const timing = createNavigationTiming();
    const record = vi.fn();

    timing.start();
    timing.settle(record);
    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    frames[0]?.(0);
    frames[1]?.(0);

    expect(record).not.toHaveBeenCalled();
  });
});
