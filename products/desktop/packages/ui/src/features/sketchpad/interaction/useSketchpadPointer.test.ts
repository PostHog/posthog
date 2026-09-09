import {
  emptySketchpadSnapshot,
  SKETCHPAD_CHANNEL,
  sketchpadFragmentSchema,
} from "@posthog/shared";
import { act, fireEvent, renderHook } from "@testing-library/react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { expect, it, vi } from "vitest";
import { useSketchpadPointer } from "./useSketchpadPointer";

it.each(["move", "resize"] as const)(
  "continues %s after an unrelated pointer ends and stops on blur",
  (kind) => {
    const fragment = sketchpadFragmentSchema.parse({
      id: "note",
      code: "export default () => null",
      x: 0,
      y: 0,
      w: 200,
      h: 100,
    });
    const applyLocal = vi.fn();
    const target = document.createElement("div");
    target.setPointerCapture = vi.fn();
    target.hasPointerCapture = vi.fn(() => true);
    target.releasePointerCapture = vi.fn();
    const { result, unmount } = renderHook(() =>
      useSketchpadPointer({
        paneRect: { left: 0, top: 0, width: 800, height: 600 },
        viewport: { x: 0, y: 0, zoom: 1 },
        setViewport: vi.fn(),
        getSnapshot: () => ({
          ...emptySketchpadSnapshot(),
          fragments: [fragment],
        }),
        applyLocal,
        getSelectedIds: () => [fragment.id],
        setSelection: vi.fn(),
        toggleSelection: vi.fn(),
      }),
    );
    const event = {
      currentTarget: target,
      pointerId: 1,
      clientX: 0,
      clientY: 0,
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    } as unknown as ReactPointerEvent;
    act(() =>
      kind === "move"
        ? result.current.startMove(fragment.id, event)
        : result.current.startResize(fragment.id, "se", event),
    );
    fireEvent.pointerUp(window, { pointerId: 2 });
    fireEvent.pointerMove(window, { pointerId: 1, clientX: 24, clientY: 24 });
    expect(applyLocal).toHaveBeenLastCalledWith([
      {
        type: "update_fragment",
        id: "note",
        patch:
          kind === "move" ? { x: 24, y: 24 } : { x: 0, y: 0, w: 224, h: 128 },
      },
    ]);
    fireEvent.blur(window);
    expect(result.current.gesture.kind).toBe("none");
    expect(target.releasePointerCapture).toHaveBeenCalledWith(1);
    applyLocal.mockClear();
    fireEvent.pointerMove(window, { pointerId: 1, clientX: 48, clientY: 48 });
    expect(applyLocal).not.toHaveBeenCalled();
    unmount();
  },
);

it("cancels a marquee without committing selection", () => {
  const setSelection = vi.fn();
  const { result, unmount } = renderHook(() =>
    useSketchpadPointer({
      paneRect: { left: 0, top: 0, width: 800, height: 600 },
      viewport: { x: 0, y: 0, zoom: 1 },
      setViewport: vi.fn(),
      getSnapshot: emptySketchpadSnapshot,
      applyLocal: vi.fn(),
      getSelectedIds: () => [],
      setSelection,
      toggleSelection: vi.fn(),
    }),
  );
  act(() =>
    result.current.onFrameBackgroundPointer({
      channel: SKETCHPAD_CHANNEL,
      type: "background-pointer",
      phase: "down",
      button: 0,
      clientX: 0,
      clientY: 0,
      shiftKey: false,
      altKey: false,
      metaKey: false,
      ctrlKey: false,
    }),
  );
  fireEvent.pointerMove(window, { clientX: 100, clientY: 100 });
  expect(result.current.marquee).toMatchObject({ width: 100, height: 100 });
  fireEvent.pointerCancel(window);
  expect(result.current.marquee).toBeNull();
  expect(setSelection).not.toHaveBeenCalled();
  unmount();
});
