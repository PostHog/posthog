import { XIcon } from "@phosphor-icons/react";
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
import { useAppView } from "@posthog/ui/router/useAppView";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import type { ReactNode } from "react";
import { BackgroundTileProvider } from "./backgroundTile";
import { TileDropZones } from "./TileDropZones";
import { TileTabContent } from "./TileTabContent";

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
  const view = useAppView();
  const { data: tasks } = useTasks();
  const task =
    view.type === "task-detail"
      ? tasks?.find((t) => t.id === view.taskId)
      : undefined;
  return (
    <ChromeBar
      inset={content ? "control" : "text"}
      className="bg-background"
      actions={<RemoveButton tab={tab} onUntile={onUntile} />}
    >
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
  isDragging: boolean;
  groupFull: boolean;
  onActivate: (tab: BrowserTab) => void;
  onUntile: (tab: BrowserTab) => void;
  children?: ReactNode;
}

export function TabTile({
  tab,
  isActive,
  isDragging,
  groupFull,
  onActivate,
  onUntile,
  children,
}: TabTileProps) {
  return (
    <div
      className={cn(
        "relative flex h-full min-h-0 flex-col overflow-hidden",
        !isActive && "opacity-90",
      )}
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
          <TileName tab={tab} isActive={false} onActivate={onActivate} />
        </ChromeBar>
      )}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {isActive ? (
          children
        ) : (
          <BackgroundTileProvider value={true}>
            <TileTabContent tab={tab} onActivate={() => onActivate(tab)} />
          </BackgroundTileProvider>
        )}
      </div>
      {isDragging && <TileDropZones tabId={tab.id} disabled={groupFull} />}
    </div>
  );
}
