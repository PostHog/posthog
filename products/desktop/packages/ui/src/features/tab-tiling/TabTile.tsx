import { useDraggable } from "@dnd-kit/react";
import { DotsSixVerticalIcon, XIcon } from "@phosphor-icons/react";
import { Button, cn, Text } from "@posthog/quill";
import type { BrowserTab } from "@posthog/shared";
import {
  isTabAppView,
  TAB_APP_VIEW_META,
} from "@posthog/ui/features/browser-tabs/tabAppViews";
import { ActivityDetailCloseButton } from "@posthog/ui/features/canvas/components/ActivityDetailCloseButton";
import { useActivitySelection } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { TaskHeaderActions } from "@posthog/ui/features/task-detail/components/TaskHeaderActions";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import type { ReactNode } from "react";
import { BackgroundTileProvider } from "./backgroundTile";
import { TileDropZones } from "./TileDropZones";
import { TileTabContent } from "./TileTabContent";
import { TILE_TAB_DRAG_TYPE, type TileTabDragData } from "./tileDrag";

function tileLabel(tab: BrowserTab): string {
  if (tab.viewState?.title) return tab.viewState.title;
  if (tab.appView && isTabAppView(tab.appView)) {
    return TAB_APP_VIEW_META[tab.appView].label;
  }
  return "New tab";
}

function tileIcon(tab: BrowserTab): ReactNode {
  if (tab.appView && isTabAppView(tab.appView)) {
    return TAB_APP_VIEW_META[tab.appView].icon;
  }
  return null;
}

function useTileDrag(tabId: string) {
  const data: TileTabDragData = { type: TILE_TAB_DRAG_TYPE, tabId };
  return useDraggable({ id: `tile-tab-${tabId}`, data, feedback: "clone" });
}

function TilePill({
  tab,
  isActive,
  onActivate,
}: {
  tab: BrowserTab;
  isActive: boolean;
  onActivate: (tab: BrowserTab) => void;
}) {
  const label = tileLabel(tab);
  const icon = tileIcon(tab);
  const { ref, isDragSource } = useTileDrag(tab.id);
  return (
    <button
      ref={ref}
      type="button"
      title={label}
      onClick={() => {
        if (!isActive) onActivate(tab);
      }}
      className={cn(
        "flex h-6 min-w-0 max-w-[280px] cursor-grab items-center gap-1.5 rounded-md px-1.5 text-left",
        isActive
          ? "bg-background font-medium shadow-xs ring-1 ring-border"
          : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
        isDragSource && "bg-background shadow-lg ring-1 ring-border",
      )}
    >
      <DotsSixVerticalIcon size={12} className="shrink-0 opacity-60" />
      {icon && <span className="flex shrink-0 items-center">{icon}</span>}
      <Text className="truncate text-xs">{label}</Text>
    </button>
  );
}

function ActiveTileHeader({
  tab,
  onActivate,
  onUntile,
}: {
  tab: BrowserTab;
  onActivate: (tab: BrowserTab) => void;
  onUntile: (tab: BrowserTab) => void;
}) {
  const activitySelection = useActivitySelection();
  const { data: tasks } = useTasks();
  const task = tab.taskId ? tasks?.find((t) => t.id === tab.taskId) : undefined;
  return (
    <ChromeBar
      inset="control"
      className="bg-background"
      actions={<RemoveButton tab={tab} onUntile={onUntile} />}
    >
      <TilePill tab={tab} isActive onActivate={onActivate} />
      <div className="min-w-0 flex-1" />
      {task && <TaskHeaderActions task={task} />}
      {activitySelection?.kind === "task" && <ActivityDetailCloseButton />}
    </ChromeBar>
  );
}

function RemoveButton({
  tab,
  onUntile,
}: {
  tab: BrowserTab;
  onUntile: (tab: BrowserTab) => void;
}) {
  return (
    <Button
      size="icon-sm"
      aria-label="Remove from split"
      className="shrink-0"
      onClick={() => onUntile(tab)}
    >
      <XIcon size={12} />
    </Button>
  );
}

interface TabTileProps {
  tab: BrowserTab;
  isActive: boolean;
  dropTarget: boolean;
  groupFull: boolean;
  onActivate: (tab: BrowserTab) => void;
  onUntile: (tab: BrowserTab) => void;
}

export function TabTile({
  tab,
  isActive,
  dropTarget,
  groupFull,
  onActivate,
  onUntile,
}: TabTileProps) {
  return (
    <div
      className={cn(
        "relative flex h-full min-h-0 flex-col overflow-hidden",
        !isActive && "opacity-90",
      )}
      data-tile={tab.id}
      data-active={isActive || undefined}
    >
      {isActive ? (
        <ActiveTileHeader
          tab={tab}
          onActivate={onActivate}
          onUntile={onUntile}
        />
      ) : (
        <ChromeBar
          inset="control"
          className="bg-muted"
          actions={<RemoveButton tab={tab} onUntile={onUntile} />}
        >
          <TilePill tab={tab} isActive={false} onActivate={onActivate} />
          <div className="min-w-0 flex-1" />
        </ChromeBar>
      )}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <BackgroundTileProvider value={true}>
          <TileTabContent tab={tab} onActivate={onActivate} />
        </BackgroundTileProvider>
      </div>
      {dropTarget && <TileDropZones tabId={tab.id} disabled={groupFull} />}
    </div>
  );
}
