import { afterEach, describe, expect, it, vi } from "vitest";
import { createNavigationTiming } from "./navigationTiming";

describe("createNavigationTiming", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function stubVisibility(state: DocumentVisibilityState): void {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue(state);
  }

  it.each(["visible", "hidden"] as const)(
    "records the duration when the route settles while %s",
    (visibility) => {
      stubVisibility(visibility);
      vi.spyOn(performance, "now")
        .mockReturnValueOnce(100)
        .mockReturnValueOnce(175);
      const timing = createNavigationTiming();
      const record = vi.fn();

      timing.start();
      timing.settle(record);

      expect(record).toHaveBeenCalledWith(75, visibility);
    },
  );

  it("uses the latest navigation start", () => {
    stubVisibility("visible");
    vi.spyOn(performance, "now")
      .mockReturnValueOnce(100)
      .mockReturnValueOnce(200)
      .mockReturnValueOnce(275);
    const timing = createNavigationTiming();
    const record = vi.fn();

    timing.start();
    timing.start();
    timing.settle(record);

    expect(record).toHaveBeenCalledWith(75, "visible");
  });

  it("does not record before navigation starts", () => {
    const timing = createNavigationTiming();
    const record = vi.fn();

    timing.settle(record);

    expect(record).not.toHaveBeenCalled();
  });
});
