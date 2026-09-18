import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { useTileLayoutStore } from "./tileLayoutStore";
import { groupForTab, type TileEdge, tabIdsIn } from "./tileTree";

export type TileSource = "strip" | "tile" | "sidebar";

export function tileBeside(
  tabId: string,
  targetTabId: string,
  edge: TileEdge,
  source: TileSource,
): void {
  const store = useTileLayoutStore.getState();
  store.tileTab(tabId, targetTabId, edge);
  const group = groupForTab(store.groups, tabId);
  track(ANALYTICS_EVENTS.BROWSER_TAB_TILED, {
    edge,
    source,
    tile_count: group ? tabIdsIn(group.root).length : 0,
  });
}

export function untileTracked(tabId: string): void {
  const store = useTileLayoutStore.getState();
  const group = groupForTab(store.groups, tabId);
  const remaining = group ? tabIdsIn(group.root).length - 1 : 0;
  store.untileTab(tabId);
  track(ANALYTICS_EVENTS.BROWSER_TAB_UNTILED, {
    tile_count: remaining > 1 ? remaining : 0,
  });
}
