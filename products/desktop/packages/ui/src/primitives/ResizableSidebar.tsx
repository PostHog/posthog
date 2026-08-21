import { SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
import { PEEK_CLOSE_MARGIN } from "@posthog/ui/primitives/hooks/useSidebarEdgeHoverPeek";
import { ResizeHandle } from "@posthog/ui/primitives/ResizeHandle";
import React from "react";

// Linear-style drag-to-close: dragging the handle clamps at SIDEBAR_MIN_WIDTH,
// but pulling well past it toward the edge collapses the sidebar. While the
// button is still held, dragging back out pops it open again. The reopen line
// sits slightly outside the collapse line so the boundary can't jitter.
const DRAG_COLLAPSE_AT = SIDEBAR_MIN_WIDTH * 0.5;
const DRAG_REOPEN_AT = DRAG_COLLAPSE_AT + 16;

export const SLIDE_MS = 200;

interface ResizableSidebarProps {
  children: React.ReactNode;
  open: boolean;
  width: number;
  setWidth: (width: number) => void;
  isResizing: boolean;
  setIsResizing: (isResizing: boolean) => void;
  side: "left" | "right";
  // Floor for drag-resize. Defaults to SIDEBAR_MIN_WIDTH; callers whose chrome
  // needs more room can raise it.
  minWidth?: number;
  // What the column keeps while closed. Zero collapses it away, which is what
  // a sidebar wants; a caller that pins chrome over this column gives that
  // chrome's width, so the content pane never reaches under it.
  collapsedWidth?: number;
  // Enables drag-to-close/reopen. Without it, dragging just clamps at min.
  setOpen?: (open: boolean) => void;
  // While closed, the panel can "peek" — slide out over the content as a
  // floating overlay (hover-reveal). The enter/leave handlers let the caller
  // keep the peek alive while the pointer is over the panel itself; dismiss
  // hides it immediately (drag-to-close of the floating panel).
  peek?: boolean;
  onPeekEnter?: () => void;
  onPeekLeave?: () => void;
  onPeekDismiss?: () => void;
  // What the resize grip says once the pointer has rested on it. Defaults to
  // the bare "Resize"; a panel with a shortcut of its own passes that too.
  resizeTooltip?: React.ReactNode;
  // Off when the child draws its own frame; two owners of an edge double it.
  drawEdge?: boolean;
}

export const ResizableSidebar: React.FC<ResizableSidebarProps> = ({
  children,
  open,
  width,
  setWidth,
  isResizing,
  setIsResizing,
  side,
  minWidth = SIDEBAR_MIN_WIDTH,
  collapsedWidth = 0,
  setOpen,
  peek = false,
  onPeekEnter,
  onPeekLeave,
  onPeekDismiss,
  resizeTooltip = "Resize",
  drawEdge = true,
}) => {
  // Whether the active drag started on the docked sidebar or the floating
  // (peek) one — dragging back out must restore the same mode it closed from.
  const dragOriginRef = React.useRef<"docked" | "overlay">("docked");
  // Width when the drag began: a drag-to-close clamps the store width down to
  // SIDEBAR_MIN_WIDTH on the way to the edge, so if the drag ends closed we
  // put this back — the next open should restore the user's chosen width.
  const dragStartWidthRef = React.useRef(width);
  // Whether the drag has closed the sidebar. Tracked in a ref, synchronously
  // with the mousemove that closes it — mouseup can fire before React
  // re-registers the listeners with the post-close open/peek values, so the
  // closure state can't be trusted for the width restore.
  const dragEndedClosedRef = React.useRef(false);
  // The panel's anchored edge in window coordinates — its left for a left-hand
  // panel, its right for a right-hand one. Width is the pointer's distance from
  // it, so a panel that doesn't start at the window edge still tracks the
  // cursor. Captured on mousedown: resizing moves the far edge, never this one.
  const boxRef = React.useRef<HTMLDivElement | null>(null);
  const anchorRef = React.useRef(0);

  const handleDragStart = () => {
    dragOriginRef.current = open ? "docked" : "overlay";
    dragStartWidthRef.current = width;
    dragEndedClosedRef.current = false;
    const rect = boxRef.current?.getBoundingClientRect();
    anchorRef.current = rect
      ? side === "left"
        ? rect.left
        : rect.right
      : side === "left"
        ? 0
        : window.innerWidth;
  };

  const pointerWidth = (e: MouseEvent) =>
    side === "left"
      ? e.clientX - anchorRef.current
      : anchorRef.current - e.clientX;

  const handleDrag = (e: MouseEvent) => {
    const pointer = pointerWidth(e);
    const clamped = Math.max(
      minWidth,
      Math.min(window.innerWidth * 0.5, pointer),
    );

    if (open) {
      if (pointer < DRAG_COLLAPSE_AT && setOpen) {
        setOpen(false);
        dragEndedClosedRef.current = true;
        return;
      }
      setWidth(clamped);
      return;
    }

    if (peek) {
      if (pointer < DRAG_COLLAPSE_AT) {
        onPeekDismiss?.();
        dragEndedClosedRef.current = true;
        return;
      }
      setWidth(clamped);
      return;
    }

    // Closed mid-drag and still holding: dragging back out pops it open in
    // whichever mode the drag started from.
    if (pointer >= DRAG_REOPEN_AT) {
      if (dragOriginRef.current === "docked" && setOpen) setOpen(true);
      else onPeekEnter?.();
      dragEndedClosedRef.current = false;
      setWidth(clamped);
    }
  };

  const handleDragEnd = (e: MouseEvent) => {
    // The collapse walk clamped the stored width to min on the way down.
    if (dragEndedClosedRef.current) setWidth(dragStartWidthRef.current);
    // Released well clear of a floating panel: the peek has been left behind.
    if (!open && peek && pointerWidth(e) > width + PEEK_CLOSE_MARGIN) {
      onPeekLeave?.();
    }
  };

  const isLeft = side === "left";
  // Closed = overlay mode: the box collapses to 0 width but the panel stays
  // mounted as an absolutely positioned layer that peek slides in and out.
  // A column that keeps a width while closed stays docked: there is no edge to
  // peek out from, and its caller draws in the space it holds.
  const isOverlay = !open && collapsedWidth === 0;
  const overlayVisible = isOverlay && peek;

  // While the panel slides, the resize handle sweeps under a stationary
  // pointer and picks up a stale :hover (browsers only recompute hover on
  // pointer moves) — the primary line would stick on. Any open/peek flip
  // starts a slide, so disarm the handle inline during that same render (a
  // grab in progress keeps it live), then re-arm once the slide is over.
  const [handleArmed, setHandleArmed] = React.useState(true);
  const [prevSlideState, setPrevSlideState] = React.useState({
    open,
    overlayVisible,
  });
  if (
    prevSlideState.open !== open ||
    prevSlideState.overlayVisible !== overlayVisible
  ) {
    setPrevSlideState({ open, overlayVisible });
    setHandleArmed(false);
  }
  React.useEffect(() => {
    if (handleArmed) return;
    // Slightly past the 200ms slide; timer-based so reduced-motion (no
    // transitionend) can't leave the handle disarmed.
    const timer = setTimeout(() => setHandleArmed(true), 250);
    return () => clearTimeout(timer);
  }, [handleArmed]);

  return (
    <div
      ref={boxRef}
      style={{
        width: open ? `${width}px` : `${collapsedWidth}px`,
        minWidth: open ? `${width}px` : `${collapsedWidth}px`,
        maxWidth: open ? `${width}px` : `${collapsedWidth}px`,
        borderLeft:
          drawEdge && !isLeft && open ? "1px solid var(--border)" : "none",
        borderRight:
          drawEdge && isLeft && open ? "1px solid var(--border)" : "none",
      }}
      className="relative h-full shrink-0"
    >
      <div
        style={{
          width: `${width}px`,
          ...(isOverlay
            ? {
                transform: overlayVisible
                  ? "translateX(0)"
                  : isLeft
                    ? "translateX(-100%)"
                    : "translateX(100%)",
                pointerEvents: overlayVisible ? "auto" : "none",
                willChange: "transform",
                // Track the pointer frame-for-frame while resizing the
                // floating panel, but let a drag-to-dismiss (peek flips off
                // mid-drag) fall through to the slide-out transition.
                transition: isResizing && overlayVisible ? "none" : undefined,
              }
            : // Docked keeps the same animated transform so the open flip
              // continues the slide (-100% → 0) in lockstep with the box
              // width — without it the panel snaps in ahead of the content.
              { transform: "translateX(0)" }),
        }}
        className={
          isOverlay
            ? `absolute inset-y-0 z-50 flex h-full min-w-0 flex-col border-border bg-chrome transition-transform duration-200 ease-out motion-reduce:transition-none ${isLeft ? "left-0" : "right-0"} ${
                drawEdge ? (isLeft ? "border-r" : "border-l") : ""
              } ${
                // Shadow only while shown — at translateX(-100%) the panel's
                // edge sits exactly on x=0 and an always-on shadow would paint
                // a sliver over the content.
                overlayVisible ? "shadow-lg" : ""
              }`
            : "relative flex h-full min-w-0 flex-col transition-transform duration-200 ease-out motion-reduce:transition-none"
        }
      >
        {children}
        {/* Rides along in both the docked and floating states, and stays
            mounted through a drag that closes the panel - it owns the gesture's
            listeners, so unmounting it mid-drag would strand them. */}
        {(open || overlayVisible || isResizing) && (
          <ResizeHandle
            edge={isLeft ? "right" : "left"}
            tooltip={resizeTooltip}
            isResizing={isResizing}
            setIsResizing={setIsResizing}
            armed={handleArmed}
            onDragStart={handleDragStart}
            onDrag={handleDrag}
            onDragEnd={handleDragEnd}
          />
        )}
      </div>
    </div>
  );
};
