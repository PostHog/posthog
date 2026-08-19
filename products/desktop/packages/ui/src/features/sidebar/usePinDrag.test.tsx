import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePinDragStore } from "./pinDragStore";
import { usePinDrag } from "./usePinDrag";

vi.mock("@posthog/ui/utils/sounds", () => ({ playTrashSound: vi.fn() }));

interface Row {
  id: string;
  pinned: boolean;
}

const dragStartEvent = () =>
  ({
    clientX: 10,
    clientY: 20,
    currentTarget: {
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 200 }),
    },
    dataTransfer: { setDragImage: vi.fn() },
  }) as unknown as React.DragEvent;

const isDragging = (): boolean => usePinDragStore.getState().dragging;

describe("usePinDrag", () => {
  beforeEach(() => {
    usePinDragStore.getState().setDragging(false);
  });

  // The store outlives the hook, and every hover card in the sidebar reads it.
  // A flag stranded true takes them all down until the next completed drag.
  it("stops reporting a drag when the list unmounts under one", () => {
    const { result, unmount } = renderHook(() =>
      usePinDrag<Row>({
        isPinned: (row) => row.pinned,
        togglePin: vi.fn(),
      }),
    );

    act(() => {
      result.current.onItemDragStart(
        { id: "a", pinned: false },
        dragStartEvent(),
      );
    });
    expect(isDragging()).toBe(true);

    unmount();

    expect(isDragging()).toBe(false);
  });
});
