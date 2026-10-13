import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePinDragStore } from "./pinDragStore";
import { consumeTaskDrop } from "./taskDrag";
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
        setPinned: vi.fn(),
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

  // Toggling every dragged row would unpin the ones already in the run, so a
  // batch drop has to state what it wants rather than flip each row. One call,
  // not one per row: pinning is a scoped mutation, so a row at a time costs a
  // round trip each.
  it("pins every dragged row that is not pinned yet, and only those", () => {
    const setPinned = vi.fn();
    const rows: Row[] = [
      { id: "a", pinned: false },
      { id: "b", pinned: true },
      { id: "c", pinned: false },
    ];
    const { result } = renderHook(() =>
      usePinDrag<Row>({
        isPinned: (row) => row.pinned,
        setPinned,
        getDragSiblings: () => rows.slice(1),
      }),
    );

    act(() => {
      result.current.pinnedZoneRef.current = {
        getBoundingClientRect: () => ({
          left: 0,
          top: 0,
          right: 300,
          bottom: 300,
        }),
      } as unknown as HTMLDivElement;
      result.current.onItemDragStart(rows[0] as Row, dragStartEvent());
    });

    act(() => {
      result.current.listProps.onDrop({
        preventDefault: vi.fn(),
      } as unknown as React.DragEvent);
    });

    expect(setPinned).toHaveBeenCalledTimes(1);
    expect(setPinned).toHaveBeenCalledWith([rows[0], rows[2]], true);
  });

  // The card promises "Remove from pinned" the moment the pointer leaves the
  // run, wherever it goes, so a release nothing else claimed has to keep that
  // promise. Escape fires no drop at all, which is what separates the two:
  // reading `dropEffect` on `dragend` cannot, because both report "none".
  it.each([
    {
      released: true,
      consumed: false,
      unpins: true,
      when: "released over nothing",
    },
    {
      released: true,
      consumed: true,
      unpins: false,
      when: "released on a Command Center tile",
    },
    {
      released: false,
      consumed: false,
      unpins: false,
      when: "cancelled with Escape",
    },
  ])("$when, unpins=$unpins", ({ released, consumed, unpins }) => {
    const setPinned = vi.fn();
    const { result } = renderHook(() =>
      usePinDrag<Row>({ isPinned: (row) => row.pinned, setPinned }),
    );

    act(() => {
      result.current.onItemDragStart(
        { id: "a", pinned: true },
        dragStartEvent(),
      );
    });

    act(() => {
      if (released) {
        // The main pane's file-drop handler stops propagation on every drop, so
        // only a capture-phase listener sees the release. Dispatching on a child
        // that stops it is how this test would catch a regression to bubble.
        const target = document.createElement("div");
        document.body.appendChild(target);
        target.addEventListener("drop", (event) => {
          event.preventDefault();
          event.stopPropagation();
        });
        if (consumed) consumeTaskDrop();
        target.dispatchEvent(
          new Event("drop", { bubbles: true, cancelable: true }),
        );
        target.remove();
      }
      result.current.onItemDragEnd();
    });

    expect(setPinned).toHaveBeenCalledTimes(unpins ? 1 : 0);
    expect(isDragging()).toBe(false);
  });
});
