import { type BrowserTab, primaryWindow } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { pushTabHistoryEntry } from "@posthog/ui/features/browser-tabs/tabHistory";
import { useTabReorderStore } from "@posthog/ui/features/browser-tabs/tabReorderStore";
import { useTabsSnapshot } from "@posthog/ui/features/browser-tabs/useBrowserTabs";
import { track } from "@posthog/ui/shell/analytics";
import { useRouter, useRouterState } from "@tanstack/react-router";
import {
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
} from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { TabTile } from "./TabTile";
import { TileDropZones } from "./TileDropZones";
import {
  groupForTab,
  MAX_TILES_PER_GROUP,
  type TileNode,
  tabIdsIn,
} from "./tileLayout";
import { useTileLayoutStore } from "./tileLayoutStore";

/** Below this share a tile cannot show a usable page. */
const MIN_TILE_PERCENT = 15;

interface TileTreeProps {
  node: TileNode;
  tabsById: Map<string, BrowserTab>;
  activeTabId: string;
  /** Tab whose pill is in flight; its own tile shows no drop zones. */
  draggingTabId: string | null;
  groupFull: boolean;
  onActivate: (tab: BrowserTab) => void;
  onUntile: (tab: BrowserTab) => void;
  children: ReactNode;
}

function nodeKey(node: TileNode): string {
  return node.type === "tab" ? node.tabId : node.id;
}

function TileTree(props: TileTreeProps) {
  const { node, tabsById, activeTabId, children } = props;
  const setSplitSizes = useTileLayoutStore((s) => s.setSplitSizes);
  if (node.type === "tab") {
    const tab = tabsById.get(node.tabId);
    if (!tab) return null;
    return (
      <TabTile
        tab={tab}
        isActive={tab.id === activeTabId}
        isDragging={
          props.draggingTabId !== null && props.draggingTabId !== tab.id
        }
        groupFull={props.groupFull}
        onActivate={props.onActivate}
        onUntile={props.onUntile}
      >
        {children}
      </TabTile>
    );
  }
  const equalShare = 100 / node.children.length;
  return (
    <PanelGroup
      direction={node.direction}
      onLayout={(sizes) => setSplitSizes(node.id, sizes)}
    >
      {node.children.map((child, index) => (
        <Fragment key={nodeKey(child)}>
          {index > 0 && (
            <PanelResizeHandle
              className={
                node.direction === "horizontal"
                  ? "w-px bg-border transition-colors hover:bg-accent-8 data-[resize-handle-active]:bg-accent-8"
                  : "h-px bg-border transition-colors hover:bg-accent-8 data-[resize-handle-active]:bg-accent-8"
              }
            />
          )}
          <Panel
            id={nodeKey(child)}
            order={index}
            defaultSize={node.sizes?.[index] ?? equalShare}
            minSize={MIN_TILE_PERCENT}
          >
            <TileTree {...props} node={child} />
          </Panel>
        </Fragment>
      ))}
    </PanelGroup>
  );
}

/**
 * Wraps the route outlet. When the active tab belongs to a tiled group, the
 * outlet renders inside that tab's tile and the other tiles render their tabs
 * without the router. Otherwise the outlet fills the pane as before, and only
 * gains edge drop zones while a pill is dragged so the first split can start.
 */
export function TileLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const snapshot = useTabsSnapshot();
  const groups = useTileLayoutStore((s) => s.groups);
  const prune = useTileLayoutStore((s) => s.prune);
  const untile = useTileLayoutStore((s) => s.untileTab);
  const draggingTabId = useTabReorderStore((s) => s.draggingTabId);
  const historyTabId = useRouterState({
    select: (s) => s.location.state.tabId ?? null,
  });

  useEffect(() => {
    prune(snapshot.tabs.map((t) => t.id));
  }, [snapshot, prune]);

  // Same fallback as the strip: history names the active tab first because
  // the server's activeTabId lags a navigation by a round trip.
  const tabsById = useMemo(
    () => new Map(snapshot.tabs.map((t) => [t.id, t])),
    [snapshot.tabs],
  );
  const win = primaryWindow(snapshot);
  const activeTabId =
    (historyTabId && tabsById.has(historyTabId) ? historyTabId : null) ??
    win?.activeTabId ??
    null;

  const onActivate = useCallback(
    (tab: BrowserTab) => {
      if (tab.href) pushTabHistoryEntry(router.history, tab.href, tab.id);
    },
    [router],
  );
  const onUntile = useCallback(
    (tab: BrowserTab) => {
      const group = groupForTab(useTileLayoutStore.getState().groups, tab.id);
      const remaining = group
        ? tabIdsIn(group.root).filter((id) => id !== tab.id)
        : [];
      untile(tab.id);
      // Removing the active tile keeps the user on the split that stays.
      if (tab.id === activeTabId && remaining.length > 1) {
        const next = tabsById.get(remaining[0]);
        if (next?.href) pushTabHistoryEntry(router.history, next.href, next.id);
      }
      track(ANALYTICS_EVENTS.BROWSER_TAB_UNTILED, {
        tile_count: remaining.length,
      });
    },
    [untile, activeTabId, tabsById, router],
  );

  const group = activeTabId ? groupForTab(groups, activeTabId) : null;

  if (!group || !activeTabId) {
    return (
      <div className="relative h-full">
        {children}
        {draggingTabId && activeTabId && draggingTabId !== activeTabId && (
          <TileDropZones tabId={activeTabId} />
        )}
      </div>
    );
  }

  return (
    <div className="h-full" data-testid="tile-layout">
      <TileTree
        node={group.root}
        tabsById={tabsById}
        activeTabId={activeTabId}
        draggingTabId={draggingTabId}
        groupFull={tabIdsIn(group.root).length >= MAX_TILES_PER_GROUP}
        onActivate={onActivate}
        onUntile={onUntile}
      >
        {children}
      </TileTree>
    </div>
  );
}
