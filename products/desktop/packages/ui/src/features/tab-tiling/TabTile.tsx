import { XIcon } from "@phosphor-icons/react";
import { Button, cn, Text } from "@posthog/quill";
import type { BrowserTab } from "@posthog/shared";
import {
  isTabAppView,
  TAB_APP_VIEW_META,
} from "@posthog/ui/features/browser-tabs/tabAppViews";
import type { ReactNode } from "react";
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
 * One tile of a tiled group: a slim header naming the tab, then the page. The
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
  const label = tileLabel(tab);
  const icon = tileIcon(tab);
  return (
    <div
      className={cn(
        "relative flex h-full min-h-0 flex-col overflow-hidden",
        !isActive && "opacity-90",
      )}
      data-active={isActive || undefined}
    >
      <div
        className={cn(
          "flex h-7 shrink-0 items-center gap-1.5 border-border border-b px-2",
          isActive ? "bg-background" : "bg-muted",
        )}
      >
        {icon && <span className="flex shrink-0 items-center">{icon}</span>}
        <button
          type="button"
          className="min-w-0 flex-1 truncate text-left"
          onClick={() => {
            if (!isActive) onActivate(tab);
          }}
          title={label}
        >
          <Text
            className={cn(
              "truncate text-xs",
              isActive ? "font-medium" : "text-muted-foreground",
            )}
          >
            {label}
          </Text>
        </button>
        <Button
          size="icon-sm"
          aria-label="Remove from split"
          className="shrink-0"
          onClick={() => onUntile(tab)}
        >
          <XIcon size={12} />
        </Button>
      </div>
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {isActive ? (
          children
        ) : (
          <TileTabContent tab={tab} onActivate={() => onActivate(tab)} />
        )}
      </div>
      {isDragging && <TileDropZones tabId={tab.id} disabled={groupFull} />}
    </div>
  );
}
