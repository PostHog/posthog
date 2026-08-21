import { Toast } from "@base-ui/react/toast";
import { resolveLinkDestination } from "@posthog/ui/shell/linkDestination";
import { useEffect, useRef } from "react";

// The browser-style status bar: hovering (or keyboard-focusing) any link shows
// its destination in the bottom-left corner, so people can see where a click
// will take them before committing. Built as a Base UI toast rather than a
// bare <div> so accessibility comes for free: the viewport is a polite
// aria-live region (focused links get their destination announced) and a
// keyboard-reachable landmark.
//
// It runs on its own Toast.Provider, separate from quill's notification stack:
// this is a navigation affordance, not a notification — it must sit bottom-left,
// never stack, never auto-dismiss, and ignore the "toast notifications" setting.

const HIDE_DELAY_MS = 100;

export function LinkDestinationBar() {
  return (
    <Toast.Provider limit={1}>
      <LinkDestinationWatcher />
    </Toast.Provider>
  );
}

function LinkDestinationWatcher() {
  const manager = Toast.useToastManager();
  const { toasts } = manager;
  // The single live preview toast: base-ui's generated id plus the URL it
  // currently shows, so repeat hovers over the same link are no-ops and moves
  // between links update in place instead of re-animating.
  const currentRef = useRef<{ id: string; url: string } | null>(null);
  const hideTimerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const cancelHide = () => {
      if (hideTimerRef.current === undefined) return;
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = undefined;
    };

    const hideNow = () => {
      cancelHide();
      const current = currentRef.current;
      if (!current) return;
      // Cleared before close: the toast lingers in "ending" state until its
      // exit transition finishes, and an update() aimed at it would be lost.
      currentRef.current = null;
      manager.close(current.id);
    };

    const show = (url: string) => {
      cancelHide();
      const current = currentRef.current;
      if (current?.url === url) return;
      if (current) {
        manager.update(current.id, { description: url });
        current.url = url;
        return;
      }
      const record = { id: "", url };
      record.id = manager.add({
        description: url,
        // 0 = never auto-dismiss; the preview lives exactly as long as the
        // hover/focus does.
        timeout: 0,
        priority: "low",
        // Safety net for dismissals we did not initiate (F6 + Escape):
        // forget the toast so the next hover creates a fresh one.
        onRemove: () => {
          if (currentRef.current === record) currentRef.current = null;
        },
      });
      currentRef.current = record;
    };

    // The delay bridges the gap when the pointer travels between two adjacent
    // links (or across the padding inside one), so the bar swaps text instead
    // of blinking out and back in.
    const scheduleHide = () => {
      if (!currentRef.current) return;
      cancelHide();
      hideTimerRef.current = window.setTimeout(() => {
        hideTimerRef.current = undefined;
        hideNow();
      }, HIDE_DELAY_MS);
    };

    const handleMouseOver = (event: MouseEvent) => {
      const url = resolveLinkDestination(event.target);
      if (url) show(url);
      else scheduleHide();
    };
    // mouseover on the next element covers movement inside the window; this
    // catches the pointer leaving the window entirely.
    const handleMouseOut = (event: MouseEvent) => {
      if (event.relatedTarget === null) scheduleHide();
    };
    const handleFocusIn = (event: FocusEvent) => {
      const url = resolveLinkDestination(event.target);
      if (url) show(url);
    };
    const handleFocusOut = (event: FocusEvent) => {
      if (resolveLinkDestination(event.target)) scheduleHide();
    };
    const handleWindowBlur = () => hideNow();

    // Capture phase, so components that stopPropagation on pointer events
    // cannot strand a stale preview.
    document.addEventListener("mouseover", handleMouseOver, true);
    document.addEventListener("mouseout", handleMouseOut, true);
    document.addEventListener("focusin", handleFocusIn, true);
    document.addEventListener("focusout", handleFocusOut, true);
    window.addEventListener("blur", handleWindowBlur);
    return () => {
      document.removeEventListener("mouseover", handleMouseOver, true);
      document.removeEventListener("mouseout", handleMouseOut, true);
      document.removeEventListener("focusin", handleFocusIn, true);
      document.removeEventListener("focusout", handleFocusOut, true);
      window.removeEventListener("blur", handleWindowBlur);
      cancelHide();
      hideNow();
    };
  }, [manager]);

  // Mount the viewport only while a preview is showing: base-ui viewports
  // register a global F6 focus shortcut, and an always-mounted empty viewport
  // would steal that landmark from quill's real notification stack.
  if (toasts.length === 0) return null;

  return (
    <Toast.Portal>
      <Toast.Viewport
        aria-label="Link destination"
        // pointer-events-none: the bar is purely informational and must never
        // swallow clicks on whatever sits in the corner beneath it.
        className="pointer-events-none fixed bottom-1 left-1 z-[100]"
      >
        {toasts.map((toast) => (
          <Toast.Root
            key={toast.id}
            toast={toast}
            className="rounded-md border border-(--gray-6) bg-(--color-panel-solid) px-2 py-0.5 shadow-sm transition-opacity duration-100 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0"
          >
            <Toast.Description className="block max-w-[min(60vw,48rem)] truncate text-(--gray-11) text-xs" />
          </Toast.Root>
        ))}
      </Toast.Viewport>
    </Toast.Portal>
  );
}
