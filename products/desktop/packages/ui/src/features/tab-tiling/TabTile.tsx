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
import { useHeaderStore } from "@posthog/ui/shell/headerStore";
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

function TileGrip({ tab }: { tab: BrowserTab }) {
  const { ref, isDragSource } = useTileDrag(tab.id);
  return (
    <span
      ref={ref}
      title={`Move ${tileLabel(tab)}`}
      className={cn(
        "flex shrink-0 cursor-grab items-center rounded-sm p-0.5 text-muted-foreground hover:bg-muted",
        isDragSource && "bg-background shadow-lg ring-1 ring-border",
      )}
    >
      <DotsSixVerticalIcon size={12} />
    </span>
  );
}

function TileName({
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
  return (
    <button
      type="button"
      className="flex h-full min-w-0 flex-1 items-center gap-1.5 text-left"
      onClick={() => {
        if (!isActive) onActivate(tab);
      }}
      title={label}
    >
      {icon && <span className="flex shrink-0 items-center">{icon}</span>}
      <Text
        className={cn(
          "truncate text-xs",
          isActive ? "font-medium" : "text-muted-foreground",
        )}
      >
        {label}
      </Text>
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
  const content = useHeaderStore((state) => state.content);
  const activitySelection = useActivitySelection();
  const { data: tasks } = useTasks();
  const task = tab.taskId ? tasks?.find((t) => t.id === tab.taskId) : undefined;
  return (
    <ChromeBar
      inset={content ? "control" : "text"}
      className="bg-background"
      actions={<RemoveButton tab={tab} onUntile={onUntile} />}
    >
      <TileGrip tab={tab} />
      {content ? (
        <div className="flex h-full min-w-0 flex-1 items-center justify-between overflow-hidden">
          {content}
        </div>
      ) : (
        <TileName tab={tab} isActive onActivate={onActivate} />
      )}
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
          className="bg-muted"
          actions={<RemoveButton tab={tab} onUntile={onUntile} />}
        >
          <TileGrip tab={tab} />
          <TileName tab={tab} isActive={false} onActivate={onActivate} />
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
