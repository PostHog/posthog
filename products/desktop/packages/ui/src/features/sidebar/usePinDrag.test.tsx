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

  // Toggling every dragged row would unpin the ones already in the run, so a
  // batch drop has to state what it wants rather than flip each row.
  it("pins every dragged row that is not pinned yet, and only those", () => {
    const togglePin = vi.fn();
    const rows: Row[] = [
      { id: "a", pinned: false },
      { id: "b", pinned: true },
      { id: "c", pinned: false },
    ];
    const { result } = renderHook(() =>
      usePinDrag<Row>({
        isPinned: (row) => row.pinned,
        togglePin,
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

    expect(togglePin.mock.calls.map(([row]) => row.id)).toEqual(["a", "c"]);
  });

  // The card promises "Remove from pinned" the moment the pointer leaves the
  // run, wherever it goes. Only the list used to take the drop, so releasing
  // over the main pane showed the promise and did nothing.
  //
  // Escape cancels a drag without firing a drop, which is what separates it
  // from a release. Reading `dropEffect` on `dragend` cannot: both report
  // "none", so a cancelled drag would unpin what the user was still holding.
  it.each([
    {
      event: "drop",
      defaultPrevented: false,
      unpins: true,
      when: "released over nothing",
    },
    {
      event: "drop",
      defaultPrevented: true,
      unpins: false,
      when: "released on another drop target",
    },
    {
      event: "dragend",
      defaultPrevented: false,
      unpins: false,
      when: "cancelled with Escape",
    },
  ])("$when, unpins=$unpins", ({ event, defaultPrevented, unpins }) => {
    const togglePin = vi.fn();
    const { result } = renderHook(() =>
      usePinDrag<Row>({ isPinned: (row) => row.pinned, togglePin }),
    );

    act(() => {
      result.current.onItemDragStart(
        { id: "a", pinned: true },
        dragStartEvent(),
      );
    });

    act(() => {
      if (event === "dragend") {
        result.current.onItemDragEnd();
        return;
      }
      const drop = new Event("drop", { cancelable: true });
      if (defaultPrevented) drop.preventDefault();
      window.dispatchEvent(drop);
    });

    expect(togglePin).toHaveBeenCalledTimes(unpins ? 1 : 0);
    expect(isDragging()).toBe(false);
  });
});
