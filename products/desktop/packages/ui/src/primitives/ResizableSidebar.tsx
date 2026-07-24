import { SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
import { PEEK_CLOSE_MARGIN } from "@posthog/ui/primitives/hooks/useSidebarEdgeHoverPeek";
import { Box, Flex } from "@radix-ui/themes";
import React from "react";

// Linear-style drag-to-close: dragging the handle clamps at SIDEBAR_MIN_WIDTH,
// but pulling well past it toward the edge collapses the sidebar. While the
// button is still held, dragging back out pops it open again. The reopen line
// sits slightly outside the collapse line so the boundary can't jitter.
const DRAG_COLLAPSE_AT = SIDEBAR_MIN_WIDTH * 0.5;
const DRAG_REOPEN_AT = DRAG_COLLAPSE_AT + 16;

// Every moving part of the open/close choreography — the box width, the
// panel's translateX, and the title bar in __root — must share this exact
// curve (Tailwind's ease-out) and duration, or the panel's edge drifts ahead
// of the content edge mid-animation and the layers visibly overlap.
const SLIDE_EASING = "cubic-bezier(0, 0, 0.2, 1)";
const SLIDE_WIDTH_TRANSITION = `width 0.2s ${SLIDE_EASING}, min-width 0.2s ${SLIDE_EASING}, max-width 0.2s ${SLIDE_EASING}`;

interface ResizableSidebarProps {
  children: React.ReactNode;
  open: boolean;
  width: number;
  setWidth: (width: number) => void;
  isResizing: boolean;
  setIsResizing: (isResizing: boolean) => void;
  side: "left" | "right";
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

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    dragOriginRef.current = open ? "docked" : "overlay";
    dragStartWidthRef.current = width;
    dragEndedClosedRef.current = false;
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

      // Distance from the sidebar's window edge, regardless of side.
      const pointer =
        side === "left" ? e.clientX : window.innerWidth - e.clientX;
      const maxWidth = window.innerWidth * 0.5;
      const clamped = Math.max(SIDEBAR_MIN_WIDTH, Math.min(maxWidth, pointer));

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
          side === "left" ? e.clientX : window.innerWidth - e.clientX;
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
  const isOverlay = !open;
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
    <Box
      style={{
        width: open ? `${width}px` : "0",
        minWidth: open ? `${width}px` : "0",
        maxWidth: open ? `${width}px` : "0",
        // Suppress only while dragging the docked sidebar so it tracks the
        // pointer frame-for-frame; a drag-to-close (open flips false mid-drag)
        // re-enables it so the collapse animates instead of jump-cutting.
        // min/max-width must animate too — they clamp the rendered width, so
        // left un-transitioned they snap the box to 0 and the content jumps.
        transition: isResizing && open ? "none" : SLIDE_WIDTH_TRANSITION,
        borderLeft: !isLeft && open ? "1px solid var(--border)" : "none",
        borderRight: isLeft && open ? "1px solid var(--border)" : "none",
      }}
      className="relative h-full shrink-0"
    >
      <Flex
        direction="column"
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
            ? `absolute inset-y-0 z-50 h-full min-w-0 border-border bg-chrome transition-transform duration-200 ease-out motion-reduce:transition-none ${
                isLeft ? "left-0 border-r" : "right-0 border-l"
              } ${
                // Shadow only while shown — at translateX(-100%) the panel's
                // edge sits exactly on x=0 and an always-on shadow would paint
                // a sliver over the content.
                overlayVisible ? "shadow-lg" : ""
              }`
            : "relative h-full min-w-0 transition-transform duration-200 ease-out motion-reduce:transition-none"
        }
      >
        {children}
        {/* Resize handle lives inside the panel so it rides along in both the
            docked and floating states. */}
        {(open || overlayVisible) && (
          <Box
            onMouseDown={handleMouseDown}
            className={`no-drag group absolute top-0 bottom-0 flex w-2 cursor-col-resize justify-center bg-transparent ${
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
          </Box>
        )}
      </Flex>
      {/* Full-screen shield while dragging: keeps the col-resize cursor no
          matter what the pointer crosses (content sets its own cursors, and
          webview tabs would swallow the drag entirely). Outside the panel so
          the panel's pointer-events:none while drag-closed can't disable it. */}
      {isResizing && (
        <Box className="fixed inset-0 z-[200] cursor-col-resize" />
      )}
    </Box>
  );
};
