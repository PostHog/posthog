import { useActiveTabId } from "@posthog/ui/features/browser-tabs/useActiveTabId";
import { useTileLayoutStore } from "./tileLayoutStore";
import { groupForTab } from "./tileTree";

export function useActiveTabTiled(): boolean {
  const groups = useTileLayoutStore((s) => s.groups);
  const activeTabId = useActiveTabId();
  return activeTabId !== null && groupForTab(groups, activeTabId) !== null;
}
