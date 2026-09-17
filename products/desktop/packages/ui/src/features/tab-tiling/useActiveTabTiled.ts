import { useActiveTabId } from "@posthog/ui/features/browser-tabs/useActiveTabId";
import { groupForTab } from "./tileLayout";
import { useTileLayoutStore } from "./tileLayoutStore";

export function useActiveTabTiled(): boolean {
  const groups = useTileLayoutStore((s) => s.groups);
  const activeTabId = useActiveTabId();
  return activeTabId !== null && groupForTab(groups, activeTabId) !== null;
}
