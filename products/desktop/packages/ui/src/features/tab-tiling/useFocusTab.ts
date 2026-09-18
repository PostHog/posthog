import { useActiveTabId } from "@posthog/ui/features/browser-tabs/useActiveTabId";
import type { TabRef } from "@posthog/ui/features/browser-tabs/useGoToTab";
import { useGoToTab } from "@posthog/ui/features/browser-tabs/useGoToTab";
import { useCallback } from "react";
import { useTileLayoutStore } from "./tileLayoutStore";
import { groupForTab } from "./tileTree";

export function useFocusTab(): (tab: TabRef) => void {
  const goToTab = useGoToTab();
  const activeTabId = useActiveTabId();
  return useCallback(
    (tab: TabRef) => {
      const { groups, noteActive } = useTileLayoutStore.getState();
      const target = groupForTab(groups, tab.id);
      const shown = activeTabId ? groupForTab(groups, activeTabId) : null;
      if (target) noteActive(tab.id);
      if (target && target === shown) return;
      goToTab(tab);
    },
    [goToTab, activeTabId],
  );
}
