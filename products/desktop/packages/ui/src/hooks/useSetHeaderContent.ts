import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { type ReactNode, useLayoutEffect } from "react";

/**
 * Put this view's title row in the app header. Push `null` for a view with
 * nothing to name; the row collapses.
 *
 * `enabled` is narrower, and there is one caller: a leaf that shares a route
 * with a layout that also writes here (a report inside `/inbox/*`). Pushing
 * null from the leaf would clear the layout's title instead of leaving it
 * alone, so the leaf stands down rather than writing.
 */
export function useSetHeaderContent(content: ReactNode, enabled = true) {
  const setContent = useHeaderStore((state) => state.setContent);

  useLayoutEffect(() => {
    if (!enabled) return;
    setContent(content);

    return () => {
      setContent(null);
    };
  }, [content, enabled, setContent]);
}
