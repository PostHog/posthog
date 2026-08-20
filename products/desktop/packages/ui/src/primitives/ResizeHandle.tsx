import { Tooltip } from "@base-ui/react/tooltip";
import type { MouseEvent, ReactNode } from "react";

/**
 * How long the pointer has to rest on a grip before it explains itself. Long,
 * because a grip is a target people cross on the way to something else and a
 * tooltip that fires on every pass reads as a flicker along the edge.
 */
const TOOLTIP_DELAY_MS = 1000;

/**
 * The grab strip a resizable panel is dragged by: a hit area wide enough to
 * find, a hairline that shows up under the pointer, and the shield that keeps
 * the resize cursor through a drag - content sets its own cursors, and webview
 * tabs would swallow the drag entirely.
 *
 * The dragging itself belongs to the caller, which is the only thing that knows
 * what a width means to it; what lives here is everything a reader touches.
 */
export function ResizeHandle({
  edge,
  tooltip,
  isResizing,
  armed = true,
  onMouseDown,
}: {
  /** Which edge of its container the grip straddles. The tooltip opens that way. */
  edge: "left" | "right";
  /** Shown after the pointer rests on the grip, and follows it up and down. */
  tooltip?: ReactNode;
  isResizing: boolean;
  /**
   * False parks the grip. A panel sliding under a stationary pointer sweeps the
   * grip past it and picks up a hover the browser never recomputes, which would
   * leave the hairline lit and the tooltip counting down.
   */
  armed?: boolean;
  onMouseDown: (e: MouseEvent<HTMLButtonElement>) => void;
}) {
  const grip = (
    <button
      type="button"
      aria-label="Resize"
      // Mouse-only affordance: there is no keyboard resize model to expose a
      // focusable control for.
      tabIndex={-1}
      onMouseDown={onMouseDown}
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
        // Its own provider, rather than the app's: a grip is not part of the
        // group of tooltips that skip their delay once one of them has opened,
        // and it wants the whole wait every time.
        <Tooltip.Provider delay={TOOLTIP_DELAY_MS}>
          <Tooltip.Root
            // A drag holds the pointer on the grip, which would otherwise sit
            // out the delay and pop a tooltip over the thing being resized.
            disabled={isResizing}
            trackCursorAxis="y"
          >
            <Tooltip.Trigger render={grip} />
            <Tooltip.Portal>
              <Tooltip.Positioner
                data-quill
                data-quill-portal="tooltip"
                side={edge}
                sideOffset={8}
                className="isolate"
              >
                <Tooltip.Popup className="quill-tooltip__content flex flex-col items-start gap-1 text-left">
                  {tooltip}
                </Tooltip.Popup>
              </Tooltip.Positioner>
            </Tooltip.Portal>
          </Tooltip.Root>
        </Tooltip.Provider>
      ) : (
        grip
      )}
      {/* pointer-events-auto because a panel being drag-closed turns its own
          off, and a shield that isn't a hit target has no cursor to give. */}
      {isResizing && (
        <div className="pointer-events-auto fixed inset-0 z-[200] cursor-col-resize" />
      )}
    </>
  );
}
