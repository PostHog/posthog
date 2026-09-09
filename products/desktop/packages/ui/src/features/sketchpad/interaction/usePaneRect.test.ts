import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { usePaneRect } from "./usePaneRect";

it("measures a pane mounted after loading and follows its resize", () => {
  let resize = (): void => {};
  const disconnect = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resize = callback;
      }
      observe = vi.fn();
      disconnect = disconnect;
    },
  );
  try {
    const pane = document.createElement("div");
    const measure = vi
      .spyOn(pane, "getBoundingClientRect")
      .mockReturnValue(new DOMRect(20, 40, 800, 600));
    const { result, unmount } = renderHook(usePaneRect);
    expect(result.current.paneRect.width).toBe(0);
    act(() => result.current.paneRef(pane));
    expect(result.current.paneRect).toEqual({
      left: 20,
      top: 40,
      width: 800,
      height: 600,
    });
    measure.mockReturnValue(new DOMRect(20, 40, 500, 600));
    act(resize);
    expect(result.current.paneRect.width).toBe(500);
    unmount();
    expect(disconnect).toHaveBeenCalled();
  } finally {
    vi.unstubAllGlobals();
  }
});
