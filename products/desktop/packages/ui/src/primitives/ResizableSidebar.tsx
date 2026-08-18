import { SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
import { PEEK_CLOSE_MARGIN } from "@posthog/ui/primitives/hooks/useSidebarEdgeHoverPeek";
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

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
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
    setIsResizing(true);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  // If the component unmounts mid-drag (e.g. a route swap while holding the
  // handle), no mouseup will ever fire — reset the drag's global side effects
  // or the app is left with a col-resize cursor, text selection disabled, and
  // a stuck isResizing that makes the next mount resize on bare mousemove.
  const unmountResetRef = React.useRef({ isResizing, setIsResizing });
  unmountResetRef.current = { isResizing, setIsResizing };
  React.useEffect(
    () => () => {
      const { isResizing: active, setIsResizing: reset } =
        unmountResetRef.current;
      if (active) {
        reset(false);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    },
    [],
  );

  React.useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;

      // Distance from the panel's own anchored edge, regardless of side, which
      // is the width the pointer is asking for.
      const pointer =
        side === "left"
          ? e.clientX - anchorRef.current
          : anchorRef.current - e.clientX;
      const maxWidth = window.innerWidth * 0.5;
      const clamped = Math.max(minWidth, Math.min(maxWidth, pointer));

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
        if (dragOriginRef.current === "docked" && setOpen) {
          setOpen(true);
        } else {
          onPeekEnter?.();
        }
        dragEndedClosedRef.current = false;
        setWidth(clamped);
      }
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (!isResizing) return;
      setIsResizing(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      // Drag ended closed (drag-to-close or peek dismiss): the collapse walk
      // clamped the store width to min on the way down — restore the pre-drag
      // width so the next open comes back at the user's chosen size.
      if (dragEndedClosedRef.current) {
        setWidth(dragStartWidthRef.current);
      }
      if (!open && peek) {
        const pointer =
          side === "left"
            ? e.clientX - anchorRef.current
            : anchorRef.current - e.clientX;
        if (pointer > width + PEEK_CLOSE_MARGIN) onPeekLeave?.();
      }
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [
    setWidth,
    isResizing,
    setIsResizing,
    side,
    minWidth,
    open,
    peek,
    width,
    setOpen,
    onPeekEnter,
    onPeekLeave,
    onPeekDismiss,
  ]);

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
        borderLeft: !isLeft && open ? "1px solid var(--border)" : "none",
        borderRight: isLeft && open ? "1px solid var(--border)" : "none",
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
            ? `absolute inset-y-0 z-50 flex h-full min-w-0 flex-col border-border bg-chrome transition-transform duration-200 ease-out motion-reduce:transition-none ${
                isLeft ? "left-0 border-r" : "right-0 border-l"
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
        {/* Resize handle lives inside the panel so it rides along in both the
            docked and floating states. */}
        {(open || overlayVisible) && (
          <button
            type="button"
            aria-label={`Resize ${side} sidebar`}
            // Mouse/drag-only affordance: there is no keyboard resize model,
            // so keep it out of the tab order rather than expose a focusable
            // control that announces a resize action and does nothing.
            tabIndex={-1}
            onMouseDown={handleMouseDown}
            className={`no-drag group absolute top-0 bottom-0 flex w-2 cursor-col-resize justify-center border-0 bg-transparent p-0 ${
              handleArmed || isResizing ? "" : "pointer-events-none"
            }`}
            style={{
              left: isLeft ? undefined : -5,
              right: isLeft ? -5 : undefined,
              zIndex: 100,
            }}
          >
            <span
              className={`h-full w-px transition-colors duration-150 ease-out ${
                isResizing
                  ? "bg-primary"
                  : handleArmed
                    ? "bg-transparent delay-100 group-hover:bg-primary"
                    : "bg-transparent"
              }`}
            />
          </button>
        )}
      </div>
      {/* Full-screen shield while dragging: keeps the col-resize cursor no
          matter what the pointer crosses (content sets its own cursors, and
          webview tabs would swallow the drag entirely). Outside the panel so
          the panel's pointer-events:none while drag-closed can't disable it. */}
      {isResizing && (
        <div className="fixed inset-0 z-[200] cursor-col-resize" />
      )}
    </div>
  );
};
