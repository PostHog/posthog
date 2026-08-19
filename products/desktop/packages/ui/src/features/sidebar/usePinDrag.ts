import { usePinDragStore } from "@posthog/ui/features/sidebar/pinDragStore";
import {
  getPinDropAction,
  isPointInsideRect,
} from "@posthog/ui/features/sidebar/taskListDragAndDrop";
import { playTrashSound } from "@posthog/ui/utils/sounds";
import { type MotionValue, useMotionValue } from "framer-motion";
import {
  type DragEvent,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

/** Parks the preview card off screen between drags rather than unmounting it. */
const OFFSCREEN = -10_000;

export interface PinDrag<T> {
  item: T;
  /** Where the drag started, which is what decides whether a drop pins or unpins. */
  sourcePinned: boolean;
  /** The pointer is over the pinned run right now. */
  overPinned: boolean;
  /** The row's own width, so the card under the pointer is the row it came from. */
  previewWidth: number;
}

export interface PinDragApi<T> {
  drag: PinDrag<T> | null;
  /** Goes on the pinned run, whose box decides what counts as a pin. */
  pinnedZoneRef: RefObject<HTMLDivElement | null>;
  /** Goes on the list, which is what accepts the drop. */
  listProps: {
    onDragOver: (event: DragEvent) => void;
    onDrop: (event: DragEvent) => void;
  };
  onItemDragStart: (item: T, event: DragEvent) => void;
  onItemDragEnd: () => void;
  previewX: MotionValue<number>;
  previewY: MotionValue<number>;
}

/**
 * Drag a session in or out of a sidebar's pinned run.
 *
 * Native HTML drag rather than a pointer-driven one, because the same rows are
 * already draggable onto the command centre's tiles and a session can only have
 * one drag. That decides the shape of the rest: the browser gives no cursor
 * position outside `dragover` and swallows every keystroke for the length of a
 * drag, so the card under the pointer is moved from a window listener, and a
 * `dragend` with no drop behind it is the only cancel signal there is.
 *
 * The list is the drop target, not the window: releasing over a command centre
 * tile is that tile's drop, and must not also unpin what it filed.
 *
 * Both sidebars run this one copy. The rules it encodes were expensive to find
 * and are invisible in the code they protect — a second implementation would
 * drift off them without anything failing loudly.
 *
 * `isPinned` and `togglePin` are what the two lists disagree on: one holds
 * channel items, the other tasks. Everything else here is the same drag.
 */
export function usePinDrag<T>({
  isPinned,
  togglePin,
}: {
  isPinned: (item: T) => boolean;
  togglePin: (item: T) => void;
}): PinDragApi<T> {
  const [drag, setDrag] = useState<PinDrag<T> | null>(null);
  // The handlers below run inside native drag events, which need the live drag
  // synchronously — a render behind is a drop applied to the wrong state.
  const dragRef = useRef<PinDrag<T> | null>(null);
  const pinnedZoneRef = useRef<HTMLDivElement | null>(null);
  const pointerOffsetRef = useRef({ x: 0, y: 0 });
  const previewX = useMotionValue(OFFSCREEN);
  const previewY = useMotionValue(OFFSCREEN);

  const write = useCallback((next: PinDrag<T> | null) => {
    dragRef.current = next;
    setDrag(next);
    usePinDragStore.getState().setDragging(next !== null);
  }, []);

  const clear = useCallback(() => {
    write(null);
    previewX.set(OFFSCREEN);
    previewY.set(OFFSCREEN);
  }, [previewX, previewY, write]);

  const overPinnedAt = useCallback(
    (x: number, y: number) =>
      isPointInsideRect(
        { x, y },
        pinnedZoneRef.current?.getBoundingClientRect() ?? null,
      ),
    [],
  );

  useEffect(() => {
    const followPointer = (event: globalThis.DragEvent) => {
      const current = dragRef.current;
      if (!current) return;
      previewX.set(event.clientX - pointerOffsetRef.current.x);
      previewY.set(event.clientY - pointerOffsetRef.current.y);
      const overPinned = overPinnedAt(event.clientX, event.clientY);
      if (overPinned === current.overPinned) return;
      // Leaving the pinned run with a pinned session is the destructive turn,
      // so it gets the sound the trash gets.
      if (current.sourcePinned && !overPinned) playTrashSound();
      write({ ...current, overPinned });
    };
    // A drag whose source leaves the DOM is killed by the browser without a
    // `dragend`, and the lists poll — so the card can't rely on the row's own
    // end event alone. Once the drag is dead the pointer is a pointer again,
    // which is the signal this listener waits for.
    const endStrandedDrag = () => {
      if (dragRef.current) clear();
    };
    // Capture, so a drop target that stops propagation can't freeze the card
    // under the pointer.
    window.addEventListener("dragover", followPointer, true);
    window.addEventListener("dragend", endStrandedDrag, true);
    window.addEventListener("mouseup", endStrandedDrag, true);
    return () => {
      window.removeEventListener("dragover", followPointer, true);
      window.removeEventListener("dragend", endStrandedDrag, true);
      window.removeEventListener("mouseup", endStrandedDrag, true);
    };
  }, [clear, overPinnedAt, previewX, previewY, write]);

  const onItemDragStart = useCallback(
    (item: T, event: DragEvent) => {
      const rect = event.currentTarget.getBoundingClientRect();
      // The browser's own ghost is a translucent stamp of the row taken before
      // the list reacts to the drag. An empty one hands the job to the card,
      // which can then say what the drop will do.
      const ghost = document.createElement("div");
      ghost.style.cssText = "position:fixed;top:-10px;width:1px;height:1px";
      document.body.appendChild(ghost);
      event.dataTransfer.setDragImage(ghost, 0, 0);
      window.requestAnimationFrame(() => ghost.remove());

      pointerOffsetRef.current = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      previewX.set(rect.left);
      previewY.set(rect.top);
      write({
        item,
        sourcePinned: isPinned(item),
        overPinned: overPinnedAt(event.clientX, event.clientY),
        previewWidth: rect.width,
      });
    },
    [isPinned, overPinnedAt, previewX, previewY, write],
  );

  const onListDragOver = useCallback((event: DragEvent) => {
    const current = dragRef.current;
    if (!current) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = current.sourcePinned ? "move" : "copy";
  }, []);

  const onListDrop = useCallback(
    (event: DragEvent) => {
      const current = dragRef.current;
      if (!current) return;
      event.preventDefault();
      if (getPinDropAction(current.sourcePinned, current.overPinned) !== null) {
        togglePin(current.item);
      }
      clear();
    },
    [clear, togglePin],
  );

  return {
    drag,
    pinnedZoneRef,
    listProps: { onDragOver: onListDragOver, onDrop: onListDrop },
    onItemDragStart,
    // Reached by a cancelled drag and by a drop the list didn't take (a command
    // centre tile). A drop the list did take has already cleared.
    onItemDragEnd: clear,
    previewX,
    previewY,
  };
}
