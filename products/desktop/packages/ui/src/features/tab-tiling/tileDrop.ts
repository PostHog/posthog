import type { BrowserTabsClient } from "@posthog/ui/features/browser-tabs/browserTabsClient";
import {
  type BrowserTabDestination,
  findTabForDestination,
  openInNewBrowserTabSync,
} from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import { readMirror } from "@posthog/ui/features/browser-tabs/tabsSync";
import { readCanvasDragDetail } from "@posthog/ui/features/canvas/canvasDrag";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import {
  consumeTaskDrop,
  readTaskDragData,
} from "@posthog/ui/features/sidebar/taskDrag";
import { getCachedTask } from "@posthog/ui/features/tasks/queries";
import { tileBeside } from "./tileActions";
import { useTileLayoutStore } from "./tileLayoutStore";
import {
  groupForTab,
  MAX_TILES_PER_GROUP,
  type TileEdge,
  tabIdsIn,
} from "./tileTree";

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

export function dropIntoTile(
  client: BrowserTabsClient,
  dataTransfer: Pick<DataTransfer, "getData">,
  targetTabId: string,
  edge: TileEdge,
): void {
  const destinations = destinationsFromDrop(dataTransfer, targetTabId);
  for (const destination of destinations) {
    const target = groupForTab(
      useTileLayoutStore.getState().groups,
      targetTabId,
    );
    if (target && tabIdsIn(target.root).length >= MAX_TILES_PER_GROUP) break;
    const tabId =
      findTabForDestination(destination)?.id ??
      openInNewBrowserTabSync(client, destination, { focus: false });
    if (!tabId || tabId === targetTabId) continue;
    tileBeside(tabId, targetTabId, edge, "sidebar");
  }
}
