import { useDraggable } from "@dnd-kit/react";
import { DotsSixVerticalIcon, XIcon } from "@phosphor-icons/react";
import { Button, cn, Text } from "@posthog/quill";
import type { BrowserTab } from "@posthog/shared";
import {
  isTabAppView,
  resolveTabAppViewDisplay,
} from "@posthog/ui/features/browser-tabs/tabAppViews";
import { ActivityDetailCloseButton } from "@posthog/ui/features/canvas/components/ActivityDetailCloseButton";
import { useActivitySelection } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { TaskHeaderActions } from "@posthog/ui/features/task-detail/components/TaskHeaderActions";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import type { ReactNode } from "react";
import { TileDropZones } from "./TileDropZones";
import { TileTabContent } from "./TileTabContent";
import { TileProvider } from "./tileContext";
import { TILE_TAB_DRAG_TYPE, type TileTabDragData } from "./tileDrag";

function tileDisplay(tab: BrowserTab): { label: string; icon: ReactNode } {
  const appView =
    tab.appView && isTabAppView(tab.appView)
      ? resolveTabAppViewDisplay(tab.appView, null)
      : null;
  return {
    label: tab.viewState?.title ?? appView?.label ?? "New tab",
    icon: appView?.icon ?? null,
  };
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
  const { label, icon } = tileDisplay(tab);
  const data: TileTabDragData = { type: TILE_TAB_DRAG_TYPE, tabId: tab.id };
  const { ref } = useDraggable({
    id: `tile-tab-${tab.id}`,
    data,
    feedback: "clone",
  });
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
          ? "font-medium"
          : "text-muted-foreground hover:text-foreground",
        "data-[dnd-dragging]:bg-background data-[dnd-dragging]:shadow-lg data-[dnd-dragging]:ring-1 data-[dnd-dragging]:ring-border",
      )}
    >
      <DotsSixVerticalIcon
        size={12}
        className="shrink-0 text-muted-foreground opacity-70"
      />
      {icon && <span className="flex shrink-0 items-center">{icon}</span>}
      <Text className="truncate text-xs">{label}</Text>
    </button>
  );
}

function TileHeader({
  tab,
  isActive,
  onActivate,
  onUntile,
}: {
  tab: BrowserTab;
  isActive: boolean;
  onActivate: (tab: BrowserTab) => void;
  onUntile: (tab: BrowserTab) => void;
}) {
  const activitySelection = useActivitySelection();
  const { data: tasks } = useTasks();
  const task =
    isActive && tab.taskId
      ? tasks?.find((t) => t.id === tab.taskId)
      : undefined;
  return (
    <ChromeBar
      inset="control"
      className={isActive ? "bg-background" : "bg-muted"}
      actions={
        <>
          {isActive && activitySelection?.kind === "task" && (
            <ActivityDetailCloseButton />
          )}
          <Button
            size="icon-sm"
            aria-label="Remove from split"
            className="shrink-0"
            onClick={() => onUntile(tab)}
          >
            <XIcon size={12} />
          </Button>
        </>
      }
    >
      <div className="flex min-w-0 flex-1 items-center">
        <TilePill tab={tab} isActive={isActive} onActivate={onActivate} />
      </div>
      {task && <TaskHeaderActions task={task} />}
    </ChromeBar>
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
      <TileHeader
        tab={tab}
        isActive={isActive}
        onActivate={onActivate}
        onUntile={onUntile}
      />
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <TileProvider value={{ focused: isActive }}>
          <TileTabContent tab={tab} onActivate={onActivate} />
        </TileProvider>
      </div>
      {dropTarget && <TileDropZones tabId={tab.id} disabled={groupFull} />}
    </div>
  );
}
