import { XIcon } from "@phosphor-icons/react";
import { Button, cn, Text } from "@posthog/quill";
import type { BrowserTab } from "@posthog/shared";
import {
  isTabAppView,
  TAB_APP_VIEW_META,
} from "@posthog/ui/features/browser-tabs/tabAppViews";
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

/**
 * The active tile stands in for the pane-wide header, which hides during a
 * split: it shows what the page pushes to the header store and, on a task,
 * the task's action row. A page that pushes nothing shows the tab name.
 */
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
  /** The active tab's tile renders the route outlet passed as children. */
  isActive: boolean;
  isDragging: boolean;
  /** True when the group cannot take another tile, so drops are refused. */
  groupFull: boolean;
  onActivate: (tab: BrowserTab) => void;
  onUntile: (tab: BrowserTab) => void;
  children?: ReactNode;
}

/**
 * One tile of a tiled group: a header naming the tab, then the page. The
 * header is the only place that switches the active tab, so a click inside a
 * background page never moves the route outlet out from under it.
 */
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
