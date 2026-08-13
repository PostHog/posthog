import {
  hasDraggedFar,
  type MarqueeRow,
  marqueeSpan,
  mergeMarqueeSelection,
  rowsInMarquee,
} from "@posthog/core/sidebar/marquee";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { type RefObject, useEffect, useState } from "react";

/** Marks a row as a session the marquee can sweep up; the value is its task id. */
export const SESSION_ROW_ATTRIBUTE = "data-session-id";

const ROW_SELECTOR = `[${SESSION_ROW_ATTRIBUTE}]`;
// A press on any other control is that control's, not the start of a drag.
const CONTROL_SELECTOR = "button, input, a, [role='menuitem'], [role='tab']";

export interface MarqueeRect {
  top: number;
  height: number;
}

/**
 * Drag across the session list to select what the drag passes.
 *
 * A press that lands on a row belongs to that row — it opens it, or drags it to
 * a command centre tile — so a marquee only starts from empty space, or with Alt
 * held to say the drag is a selection rather than the row's own.
 *
 * `anchorRef` must be a non-scrolling positioned ancestor of the rows: the
 * returned rect is relative to it, and the rows are read from inside it.
 */
export function useMarqueeSelection(
  anchorRef: RefObject<HTMLElement | null>,
): MarqueeRect | null {
  const [rect, setRect] = useState<MarqueeRect | null>(null);

  useEffect(() => {
    const anchor = anchorRef.current;
    if (!anchor) return;

    let origin: { x: number; y: number } | null = null;
    let baseSelection: string[] = [];
    let additive = false;
    let dragging = false;
    // Measured once the drag starts: rows don't move under it, and re-reading
    // every row's box on each pointermove is the expensive way to find out.
    let rows: MarqueeRow[] = [];

    const readRows = (): MarqueeRow[] =>
      [...anchor.querySelectorAll<HTMLElement>(ROW_SELECTOR)].flatMap((el) => {
        const id = el.getAttribute(SESSION_ROW_ATTRIBUTE);
        if (!id) return [];
        const box = el.getBoundingClientRect();
        return [{ id, top: box.top, bottom: box.bottom }];
      });

    const stop = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stop);
      origin = null;
      dragging = false;
      setRect(null);
    };

    const onPointerMove = (e: PointerEvent) => {
      if (!origin) return;
      if (!dragging) {
        if (!hasDraggedFar(e.clientX - origin.x, e.clientY - origin.y)) return;
        dragging = true;
        rows = readRows();
      }
      // Stops the drag from turning into a text selection over the labels.
      e.preventDefault();

      const span = marqueeSpan(origin.y, e.clientY);
      const anchorTop = anchor.getBoundingClientRect().top;
      setRect({
        top: span.top - anchorTop,
        height: span.bottom - span.top,
      });
      useTaskSelectionStore
        .getState()
        .setSelectedTaskIds(
          mergeMarqueeSelection(
            baseSelection,
            rowsInMarquee(span, rows),
            additive,
          ),
        );
    };

    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const target = e.target as Element | null;
      if (!target) return;
      const onRow = target.closest(ROW_SELECTOR);
      if (onRow && !e.altKey) return;
      if (!onRow && target.closest(CONTROL_SELECTOR)) return;

      origin = { x: e.clientX, y: e.clientY };
      additive = e.metaKey || e.ctrlKey;
      baseSelection = useTaskSelectionStore.getState().selectedTaskIds;
      dragging = false;
      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", stop);
    };

    anchor.addEventListener("pointerdown", onPointerDown);
    return () => {
      anchor.removeEventListener("pointerdown", onPointerDown);
      stop();
    };
  }, [anchorRef]);

  return rect;
}
