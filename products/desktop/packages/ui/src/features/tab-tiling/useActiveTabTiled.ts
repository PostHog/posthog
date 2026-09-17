import { useActiveTabId } from "@posthog/ui/features/browser-tabs/useActiveTabId";
import { groupForTab } from "./tileLayout";
import { useTileLayoutStore } from "./tileLayoutStore";

/**
 * True while the content pane shows a split. The pane-wide header rows hide
 * then: a title that names one tile above several is misleading, so the active
 * tile's own header carries it instead.
 */
export function useActiveTabTiled(): boolean {
  const groups = useTileLayoutStore((s) => s.groups);
  const activeTabId = useActiveTabId();
  return activeTabId !== null && groupForTab(groups, activeTabId) !== null;
}
