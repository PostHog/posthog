import { Tooltip } from "@base-ui/react/tooltip";
import React from "react";
import { createPortal } from "react-dom";

/** Long: a grip is a target people cross on the way elsewhere. */
const TOOLTIP_DELAY_MS = 1000;

function setDragCursor(dragging: boolean): void {
  document.body.style.cursor = dragging ? "col-resize" : "";
  document.body.style.userSelect = dragging ? "none" : "";
}

/**
 * The grab strip a resizable panel is dragged by, and the whole gesture behind
 * it: the hit area, the hairline, the window-wide cursor shield, and the
 * mousemove/mouseup lifecycle. Callers supply only what a width means to them.
 */
export function ResizeHandle({
  edge,
  tooltip,
  isResizing,
  setIsResizing,
  armed = true,
  onDragStart,
  onDrag,
  onDragEnd,
}: {
  /** Which edge of its container the grip straddles. The tooltip opens that way. */
  edge: "left" | "right";
  /** Shown once the pointer rests on the grip, and follows it up and down. */
  tooltip?: React.ReactNode;
  isResizing: boolean;
  setIsResizing: (isResizing: boolean) => void;
  /**
   * False parks the grip. A panel sliding under a stationary pointer leaves a
   * hover the browser never recomputes, lighting the hairline for nothing.
   */
  armed?: boolean;
  /** Capture whatever the drag measures from. */
  onDragStart?: () => void;
  onDrag: (event: MouseEvent) => void;
  onDragEnd?: (event: MouseEvent) => void;
}) {
  const handlers = React.useRef({ onDrag, onDragEnd, setIsResizing });
  React.useEffect(() => {
    handlers.current = { onDrag, onDragEnd, setIsResizing };
  });

  React.useEffect(() => {
    if (!isResizing) return;

    const move = (event: MouseEvent) => handlers.current.onDrag(event);
    const up = (event: MouseEvent) => {
      handlers.current.setIsResizing(false);
      setDragCursor(false);
      handlers.current.onDragEnd?.(event);
    };

    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
    return () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      // Unmounting mid-drag means no mouseup ever lands, which would strand the
      // cursor and a stuck isResizing. Redundant when the drag ended normally.
      setDragCursor(false);
      handlers.current.setIsResizing(false);
    };
  }, [isResizing]);

  const grip = (
    <button
      type="button"
      aria-label="Resize"
      // Mouse-only: there is no keyboard resize model to expose a control for.
      tabIndex={-1}
      onMouseDown={(event) => {
        event.preventDefault();
        onDragStart?.();
        setIsResizing(true);
        setDragCursor(true);
      }}
      className={`no-drag group absolute inset-y-0 z-100 flex w-3 cursor-col-resize justify-center border-0 bg-transparent p-0 ${
        edge === "left" ? "-left-1.5" : "-right-1.5"
      } ${armed || isResizing ? "" : "pointer-events-none"}`}
    >
      <span
        className={`h-full w-px transition-colors duration-150 ease-out ${
          isResizing
            ? "bg-primary"
            : armed
              ? "bg-transparent delay-100 group-hover:bg-primary"
              : "bg-transparent"
        }`}
      />
    </button>
  );

  return (
    <>
      {tooltip ? (
        // Its own provider: a grip is not part of the group that skips its
        // delay once one tooltip has opened.
        <Tooltip.Provider delay={TOOLTIP_DELAY_MS}>
          <Tooltip.Root disabled={isResizing} trackCursorAxis="y">
            <Tooltip.Trigger render={grip} />
            <Tooltip.Portal>
              <Tooltip.Positioner
                data-quill
                data-quill-portal="tooltip"
                side={edge}
                sideOffset={8}
                className="isolate"
              >
                {/* Uniform padding over quill's 6px/12px split, and a line
                    height that hugs the text: a kbd chip fills its line box,
                    so leading above a bare line reads as a lopsided box. */}
                <Tooltip.Popup className="quill-tooltip__content flex flex-col items-start gap-1 p-2 text-left leading-tight">
                  {tooltip}
                </Tooltip.Popup>
              </Tooltip.Positioner>
            </Tooltip.Portal>
          </Tooltip.Root>
        </Tooltip.Provider>
      ) : (
        grip
      )}
      {/* Portaled to the body: every caller sits inside a transformed panel,
          which would otherwise be the containing block for a fixed shield and
          confine it there. pointer-events-auto because a drag-closed panel
          turns its own off, and a shield that is no hit target gives no cursor. */}
      {isResizing &&
        createPortal(
          <div className="pointer-events-auto fixed inset-0 z-[200] cursor-col-resize" />,
          document.body,
        )}
    </>
  );
}
