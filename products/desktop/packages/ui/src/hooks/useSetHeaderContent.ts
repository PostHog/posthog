import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { type ReactNode, useLayoutEffect } from "react";

/**
 * Push `null` for a view with nothing to name; the row collapses. `enabled` is
 * for the one leaf that shares a route with a layout writing here too: pushing
 * null there would clear the layout's title instead of leaving it alone.
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
