import {
  openTab as openTabLocal,
  primaryWindow,
  setWindowActiveTab,
} from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { BrowserTabsClient } from "@posthog/ui/features/browser-tabs/browserTabsClient";
import type { BrowserTabDestination } from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import {
  applyLocalTransform,
  persistWrite,
  readMirror,
} from "@posthog/ui/features/browser-tabs/tabsSync";
import { readCanvasDragDetail } from "@posthog/ui/features/canvas/canvasDrag";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import {
  consumeTaskDrop,
  readTaskDragData,
} from "@posthog/ui/features/sidebar/taskDrag";
import { getCachedTask } from "@posthog/ui/features/tasks/queries";
import { track } from "@posthog/ui/shell/analytics";
import { useTileLayoutStore } from "./tileLayoutStore";
import { groupForTab, type TileEdge, tabIdsIn } from "./tileTree";

function channelFor(
  targetTabId: string,
  explicit: string | null,
): string | null {
  if (explicit) return explicit;
  const target = readMirror().tabs.find((t) => t.id === targetTabId);
  return (
    useCurrentChannelStore.getState().currentChannelId ??
    target?.channelId ??
    null
  );
}

function taskDestination(
  taskId: string,
  targetTabId: string,
): BrowserTabDestination {
  const channelId = channelFor(targetTabId, null);
  return {
    href: channelId
      ? `/spaces/${channelId}/tasks/${taskId}`
      : `/tasks/${taskId}`,
    title: getCachedTask(taskId)?.title,
    taskId,
    channelId,
  };
}

function canvasDestination(
  canvas: { id: string; name: string; channelId: string | null },
  targetTabId: string,
): BrowserTabDestination | null {
  const channelId = channelFor(targetTabId, canvas.channelId);
  if (!channelId) return null;
  return {
    href: `/spaces/${channelId}/dashboards/${canvas.id}`,
    title: canvas.name || undefined,
    dashboardId: canvas.id,
    channelId,
  };
}

export function destinationsFromDrop(
  dataTransfer: Pick<DataTransfer, "getData">,
  targetTabId: string,
): BrowserTabDestination[] {
  const taskIds = readTaskDragData(dataTransfer);
  if (taskIds.length > 0) {
    consumeTaskDrop();
    return taskIds.map((taskId) => taskDestination(taskId, targetTabId));
  }
  const canvas = readCanvasDragDetail(dataTransfer);
  if (!canvas) return [];
  const destination = canvasDestination(canvas, targetTabId);
  return destination ? [destination] : [];
}

function existingTabFor(destination: BrowserTabDestination): string | null {
  const tab = readMirror().tabs.find(
    (t) =>
      (destination.taskId && t.taskId === destination.taskId) ||
      (destination.dashboardId && t.dashboardId === destination.dashboardId),
  );
  return tab?.id ?? null;
}

function openBackgroundTab(
  client: BrowserTabsClient,
  destination: BrowserTabDestination,
): string | null {
  const win = primaryWindow(readMirror());
  if (!win) return null;
  const activeTabId = win.activeTabId;
  const tabId = crypto.randomUUID();
  const input = {
    windowId: win.id,
    href: destination.href,
    viewState: destination.title ? { title: destination.title } : null,
    dashboardId: destination.dashboardId ?? null,
    taskId: destination.taskId ?? null,
    channelId: destination.channelId ?? null,
    channelSection: destination.channelSection ?? null,
    appView: destination.appView ?? null,
  };
  applyLocalTransform((snapshot) => {
    const opened = openTabLocal(snapshot, {
      ...input,
      makeId: () => tabId,
      now: Date.now,
    }).snapshot;
    return activeTabId
      ? setWindowActiveTab(opened, win.id, activeTabId)
      : opened;
  });
  void persistWrite(async () => {
    const opened = await client.openTab({ ...input, tabId });
    if (!activeTabId) return opened;
    return client.setActiveTab({ windowId: win.id, tabId: activeTabId });
  });
  return tabId;
}

export function dropIntoTile(
  client: BrowserTabsClient,
  dataTransfer: Pick<DataTransfer, "getData">,
  targetTabId: string,
  edge: TileEdge,
): void {
  const destinations = destinationsFromDrop(dataTransfer, targetTabId);
  for (const destination of destinations) {
    const tabId =
      existingTabFor(destination) ?? openBackgroundTab(client, destination);
    if (!tabId || tabId === targetTabId) continue;
    useTileLayoutStore.getState().tileTab(tabId, targetTabId, edge);
    const group = groupForTab(useTileLayoutStore.getState().groups, tabId);
    track(ANALYTICS_EVENTS.BROWSER_TAB_TILED, {
      edge,
      source: "sidebar",
      tile_count: group ? tabIdsIn(group.root).length : 0,
    });
  }
}
