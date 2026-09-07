import {
  holdSidebarPeek,
  releaseSidebarPeek,
} from "@posthog/ui/features/sidebar/sidebarPeekStore";
import { useCallback, useEffect, useRef } from "react";

// Sidebar menus render in portals; holding the peek while one is open stops the
// sidebar collapsing underneath it and stranding the menu's anchor.
export function useHoldSidebarPeek(): (open: boolean) => void {
  const holdingRef = useRef(false);

  useEffect(
    () => () => {
      if (holdingRef.current) releaseSidebarPeek();
    },
    [],
  );

  return useCallback((open: boolean) => {
    if (open === holdingRef.current) return;
    holdingRef.current = open;
    if (open) holdSidebarPeek();
    else releaseSidebarPeek();
  }, []);
}
