import { cn } from "@posthog/quill";
import type { BrowserTab } from "@posthog/shared";
import { usePinnedTabsStore } from "@posthog/ui/features/browser-tabs/pinnedTabsStore";
import { useTabReorderStore } from "@posthog/ui/features/browser-tabs/tabReorderStore";
import { useActiveTabId } from "@posthog/ui/features/browser-tabs/useActiveTabId";
import { useTabsSnapshot } from "@posthog/ui/features/browser-tabs/useBrowserTabs";
import { useGoToTab } from "@posthog/ui/features/browser-tabs/useGoToTab";
import {
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useNativeDragKind } from "./nativeDrag";
import { TabTile } from "./TabTile";
import { TileDropZones } from "./TileDropZones";
import { untileTracked } from "./tileActions";
import { useTileLayoutStore } from "./tileLayoutStore";
import {
  groupForTab,
  MAX_TILES_PER_GROUP,
  nodeId,
  type TileNode,
  tabIdsIn,
} from "./tileTree";
import { useFocusTab } from "./useFocusTab";

const MIN_TILE_PERCENT = 15;

interface TileTreeProps {
  node: TileNode;
  tabsById: Map<string, BrowserTab>;
  activeTabId: string;
  draggingTabId: string | null;
  nativeDragActive: boolean;
  groupFull: boolean;
  onActivate: (tab: BrowserTab) => void;
  onUntile: (tab: BrowserTab) => void;
}

function TileTree(props: TileTreeProps) {
  const { node, tabsById, activeTabId } = props;
  const setSplitSizes = useTileLayoutStore((s) => s.setSplitSizes);
  const liveSizes = useRef<number[] | null>(null);
  if (node.type === "tab") {
    const tab = tabsById.get(node.tabId);
    if (!tab) return null;
    return (
      <TabTile
        tab={tab}
        isActive={tab.id === activeTabId}
        dropTarget={
          props.nativeDragActive ||
          (props.draggingTabId !== null && props.draggingTabId !== tab.id)
        }
        groupFull={props.groupFull}
        onActivate={props.onActivate}
        onUntile={props.onUntile}
      />
    );
  }
  const equalShare = 100 / node.children.length;
  return (
    <PanelGroup
      direction={node.direction}
      onLayout={(sizes) => {
        liveSizes.current = sizes;
      }}
    >
      {node.children.map((child, index) => (
        <Fragment key={nodeId(child)}>
          {index > 0 && (
            <PanelResizeHandle
              onDragging={(dragging) => {
                if (!dragging && liveSizes.current) {
                  setSplitSizes(node.id, liveSizes.current);
                }
              }}
              className={cn(
                "relative z-10 bg-border transition-colors hover:bg-accent-8 data-[resize-handle-active]:bg-accent-8",
                node.direction === "horizontal" ? "w-px" : "h-px",
              )}
            />
          )}
          <Panel
            id={nodeId(child)}
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

export function TileLayout({ children }: { children: ReactNode }) {
  const goToTab = useGoToTab();
  const snapshot = useTabsSnapshot();
  const groups = useTileLayoutStore((s) => s.groups);
  const prune = useTileLayoutStore((s) => s.prune);
  const noteActive = useTileLayoutStore((s) => s.noteActive);
  const pinnedTabIds = usePinnedTabsStore((s) => s.pinnedTabIds);
  const rawDraggingTabId = useTabReorderStore((s) =>
    s.detached ? s.draggingTabId : null,
  );
  const dragSource = useTabReorderStore((s) => s.dragSource);
  const draggingTabId = useMemo(() => {
    if (!rawDraggingTabId) return null;
    if (dragSource === "tile") return rawDraggingTabId;
    const loose =
      !groupForTab(groups, rawDraggingTabId) &&
      !pinnedTabIds.includes(rawDraggingTabId);
    return loose ? rawDraggingTabId : null;
  }, [rawDraggingTabId, dragSource, groups, pinnedTabIds]);
  const activeTabId = useActiveTabId();
  const focusTab = useFocusTab(activeTabId);
  const nativeDragActive = useNativeDragKind() !== null;

  useEffect(() => {
    if (snapshot.windows.length === 0) return;
    prune(snapshot.tabs.map((t) => t.id));
  }, [snapshot, prune]);

  const tabsById = useMemo(
    () => new Map(snapshot.tabs.map((t) => [t.id, t])),
    [snapshot.tabs],
  );

  const onUntile = useCallback(
    (tab: BrowserTab) => {
      const group = groupForTab(groups, tab.id);
      const remaining = group
        ? tabIdsIn(group.root).filter((id) => id !== tab.id)
        : [];
      untileTracked(tab.id);
      if (tab.id === activeTabId && remaining.length > 1) {
        const next = tabsById.get(remaining[0]);
        if (next) goToTab(next);
      }
    },
    [groups, activeTabId, tabsById, goToTab],
  );

  const group = activeTabId ? groupForTab(groups, activeTabId) : null;

  useEffect(() => {
    if (activeTabId) noteActive(activeTabId);
  }, [activeTabId, noteActive]);

  if (!group || !activeTabId) {
    return (
      <div className="relative h-full">
        {children}
        {activeTabId &&
          (nativeDragActive ||
            (draggingTabId && draggingTabId !== activeTabId)) && (
            <TileDropZones tabId={activeTabId} />
          )}
      </div>
    );
  }

  const groupTabIds = tabIdsIn(group.root);
  const groupFull =
    groupTabIds.length >= MAX_TILES_PER_GROUP &&
    !(draggingTabId && groupTabIds.includes(draggingTabId));

  return (
    <div className="h-full" data-testid="tile-layout">
      <TileTree
        node={group.root}
        tabsById={tabsById}
        activeTabId={activeTabId}
        draggingTabId={draggingTabId}
        nativeDragActive={nativeDragActive}
        groupFull={groupFull}
        onActivate={focusTab}
        onUntile={onUntile}
      />
    </div>
  );
}
