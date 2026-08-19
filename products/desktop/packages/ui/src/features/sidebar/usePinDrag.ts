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
  /** Where the drag started, which decides whether a drop pins or unpins. */
  sourcePinned: boolean;
  overPinned: boolean;
  previewWidth: number;
}

export interface PinDragApi<T> {
  drag: PinDrag<T> | null;
  /** Goes on the pinned run, whose box decides what counts as a pin. */
  pinnedZoneRef: RefObject<HTMLDivElement | null>;
  /** Goes on the list, which accepts the drop. */
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
 * Native HTML drag, because these rows are already draggable onto Command
 * Center tiles and an element gets one drag. Three constraints follow, and none
 * of them show up in the code they shape:
 *
 * 1. The browser reports the cursor only in `dragover`, so a window listener
 *    moves the card.
 * 2. It swallows every keystroke for the length of a drag, so a `dragend` with
 *    no drop behind it is the only cancel signal.
 * 3. The list is the drop target, not the window. Releasing over a Command
 *    Center tile is that tile's drop and must not also unpin what it filed.
 */
export function usePinDrag<T>({
  isPinned,
  togglePin,
}: {
  isPinned: (item: T) => boolean;
  togglePin: (item: T) => void;
}): PinDragApi<T> {
  const [drag, setDrag] = useState<PinDrag<T> | null>(null);
  // Native drag handlers need the live drag synchronously; a render behind is a
  // drop applied to the wrong state.
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
      // Leaving the run with a pinned session is the destructive turn.
      if (current.sourcePinned && !overPinned) playTrashSound();
      write({ ...current, overPinned });
    };
    // A drag whose source leaves the DOM dies without a `dragend`, and the
    // lists poll. Once it is dead the pointer works again, which is the signal.
    const endStrandedDrag = () => {
      if (dragRef.current) clear();
    };
    // Capture, so a drop target that stops propagation can't freeze the card.
    window.addEventListener("dragover", followPointer, true);
    window.addEventListener("dragend", endStrandedDrag, true);
    window.addEventListener("mouseup", endStrandedDrag, true);
    return () => {
      window.removeEventListener("dragover", followPointer, true);
      window.removeEventListener("dragend", endStrandedDrag, true);
      window.removeEventListener("mouseup", endStrandedDrag, true);
      // The store outlives the hook. Unmounting mid-drag would strand the flag
      // true, and every hover card in the sidebar reads it.
      usePinDragStore.getState().setDragging(false);
    };
  }, [clear, overPinnedAt, previewX, previewY, write]);

  const onItemDragStart = useCallback(
    (item: T, event: DragEvent) => {
      const rect = event.currentTarget.getBoundingClientRect();
      // The browser's own ghost is stamped before the list reacts to the drag.
      // An empty one hands the job to the card.
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
    // Reached by a cancelled drag, and by a drop the list didn't take (a
    // Command Center tile). A drop the list took has already cleared.
    onItemDragEnd: clear,
    previewX,
    previewY,
  };
}
