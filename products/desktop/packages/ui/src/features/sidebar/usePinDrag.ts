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
  /**
   * Everything the drop applies to, grabbed item first. Non-empty by
   * construction: the grabbed item is prepended rather than looked up, so a
   * selection the list can't fully resolve still drops what was grabbed.
   */
  items: [T, ...T[]];
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
  getDragSiblings,
}: {
  isPinned: (item: T) => boolean;
  togglePin: (item: T) => void;
  /**
   * The items dragged alongside the grabbed one, excluding it. Absent, or
   * returning nothing, keeps the drag single-item.
   */
  getDragSiblings?: (item: T) => T[];
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

  // Toggling every dragged item would unpin the ones already pinned, so a drop
  // states what it wants and skips whatever is already there.
  const applyDrop = useCallback(
    (drag: PinDrag<T>) => {
      const action = getPinDropAction(drag.sourcePinned, drag.overPinned);
      if (action === null) return;
      for (const item of drag.items) {
        if (isPinned(item) !== action) togglePin(item);
      }
    },
    [isPinned, togglePin],
  );

  // The listeners below register once for the life of the hook. Re-registering
  // tears the effect down, and its cleanup reports the drag as over while it is
  // still under the pointer. `applyDrop` closes over callers' inline callbacks,
  // so it changes identity every render and can't be a dep.
  const applyDropRef = useRef(applyDrop);
  useEffect(() => {
    applyDropRef.current = applyDrop;
  }, [applyDrop]);

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
      // Every dragover, before anything else: the preview card promises an
      // unpin wherever the pointer leaves the run, and only a `preventDefault`
      // here makes the surface under it somewhere the drag can be released. A
      // more specific target still sets its own `dropEffect` afterwards.
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = current.sourcePinned ? "move" : "copy";
      }
      previewX.set(event.clientX - pointerOffsetRef.current.x);
      previewY.set(event.clientY - pointerOffsetRef.current.y);
      const overPinned = overPinnedAt(event.clientX, event.clientY);
      if (overPinned === current.overPinned) return;
      // Leaving the run with a pinned session is the destructive turn.
      if (current.sourcePinned && !overPinned) playTrashSound();
      write({ ...current, overPinned });
    };
    // Releasing over a surface with no drop target of its own still has to do
    // what the card promised. `defaultPrevented` says whether something more
    // specific already took this drop: a Command Center tile takes it to file
    // the session, and must not also unpin what it just filed. The list takes
    // its own and has already cleared, so this finds nothing to do.
    //
    // Bubble phase, so those handlers run first. Reading a drop rather than
    // reading `dropEffect` on `dragend` is what separates a release from an
    // Escape, which reports `none` and fires no drop at all.
    const takeDrop = (event: globalThis.DragEvent) => {
      const current = dragRef.current;
      if (!current) return;
      if (!event.defaultPrevented) applyDropRef.current(current);
      clear();
    };
    // A drag whose source leaves the DOM dies without a `dragend`, and the
    // lists poll. Once it is dead the pointer works again, which is the signal.
    const endStrandedDrag = () => {
      if (dragRef.current) clear();
    };
    // Capture, so a drop target that stops propagation can't freeze the card.
    window.addEventListener("dragover", followPointer, true);
    window.addEventListener("drop", takeDrop);
    window.addEventListener("mouseup", endStrandedDrag, true);
    return () => {
      window.removeEventListener("dragover", followPointer, true);
      window.removeEventListener("drop", takeDrop);
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
        items: [item, ...(getDragSiblings?.(item) ?? [])],
        sourcePinned: isPinned(item),
        overPinned: overPinnedAt(event.clientX, event.clientY),
        previewWidth: rect.width,
      });
    },
    [getDragSiblings, isPinned, overPinnedAt, previewX, previewY, write],
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
      applyDrop(current);
      clear();
    },
    [applyDrop, clear],
  );

  return {
    drag,
    pinnedZoneRef,
    listProps: { onDragOver: onListDragOver, onDrop: onListDrop },
    onItemDragStart,
    // Reached by a cancelled drag, which fires no drop. A released one has
    // already been taken and cleared above.
    onItemDragEnd: clear,
    previewX,
    previewY,
  };
}
