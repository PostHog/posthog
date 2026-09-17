import { useInBackgroundTile } from "@posthog/ui/features/tab-tiling/backgroundTile";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { type ReactNode, useLayoutEffect } from "react";

/**
 * Push `null` for a view with nothing to name; the row collapses. `enabled` is
 * for the one leaf that shares a route with a layout writing here too: pushing
 * null there would clear the layout's title instead of leaving it alone.
 *
 * A page in a background tile never writes: the header belongs to the active
 * tab's page, and a late-mounting tile would otherwise replace its title.
 */
export function useSetHeaderContent(content: ReactNode, enabled = true) {
  const setContent = useHeaderStore((state) => state.setContent);
  const inBackgroundTile = useInBackgroundTile();

  useLayoutEffect(() => {
    if (!enabled || inBackgroundTile) return;
    setContent(content);

    return () => {
      setContent(null);
    };
  }, [content, enabled, inBackgroundTile, setContent]);
}
