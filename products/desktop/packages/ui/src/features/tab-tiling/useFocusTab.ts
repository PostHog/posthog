import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { TabRef } from "@posthog/ui/features/browser-tabs/useGoToTab";
import { useGoToTab } from "@posthog/ui/features/browser-tabs/useGoToTab";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback } from "react";
import { useTileLayoutStore } from "./tileLayoutStore";
import { groupForTab, tabIdsIn } from "./tileTree";

export function useFocusTab(activeTabId: string | null): (tab: TabRef) => void {
  const goToTab = useGoToTab();
  return useCallback(
    (tab: TabRef) => {
      const active = activeTabId;
      const { groups, noteActive } = useTileLayoutStore.getState();
      const target = groupForTab(groups, tab.id);
      const shown = active ? groupForTab(groups, active) : null;
      if (target) noteActive(tab.id);
      if (target && target === shown) {
        if (tab.id !== active) {
          track(ANALYTICS_EVENTS.BROWSER_TAB_TILE_FOCUSED, {
            tile_count: tabIdsIn(target.root).length,
          });
        }
        return;
      }
      goToTab(tab);
    },
    [goToTab, activeTabId],
  );
}
