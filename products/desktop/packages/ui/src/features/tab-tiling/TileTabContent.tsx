import { Button, Text } from "@posthog/quill";
import type { BrowserTab } from "@posthog/shared";
import { WebsiteDashboard } from "@posthog/ui/features/canvas/components/WebsiteDashboard";
import { TaskDetail } from "@posthog/ui/features/task-detail/components/TaskDetail";
import {
  getCachedTask,
  getCachedTaskDetail,
  taskDetailQuery,
} from "@posthog/ui/features/tasks/queries";
import { pickFreshestTask } from "@posthog/ui/features/tasks/taskFreshness";
import { TaskDetailSkeleton } from "@posthog/ui/router/routeSkeletons";
import { useQuery } from "@tanstack/react-query";

/** Whether a tab can render in a tile that is not the active one. */
export function canRenderInBackgroundTile(tab: BrowserTab): boolean {
  return tab.taskId !== null || tab.dashboardId !== null;
}

function TiledTask({ taskId }: { taskId: string }) {
  const cached = getCachedTaskDetail(taskId) ?? getCachedTask(taskId) ?? null;
  const { data: fetched, isError } = useQuery(taskDetailQuery(taskId));
  const task = pickFreshestTask(fetched, cached);
  if (task) return <TaskDetail task={task} />;
  if (isError) {
    return (
      <Notice>Couldn't load this task. Refresh the app to try again.</Notice>
    );
  }
  return <TaskDetailSkeleton />;
}

function Notice({
  children,
  action,
}: {
  children: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <Text className="text-muted-foreground text-sm">{children}</Text>
      {action && (
        <Button variant="outline" size="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}

/**
 * Renders a tab's page without the router. Only the active tab owns the route
 * outlet, so every other tile mounts its page directly from the tab's cached
 * identity. Pages that read route params cannot mount this way yet; those
 * tiles offer to make their tab the active one instead.
 */
export function TileTabContent({
  tab,
  onActivate,
}: {
  tab: BrowserTab;
  onActivate: () => void;
}) {
  if (tab.taskId) return <TiledTask taskId={tab.taskId} />;
  if (tab.dashboardId)
    return <WebsiteDashboard dashboardId={tab.dashboardId} />;
  return (
    <Notice action={{ label: "Show this tab", onClick: onActivate }}>
      This page only shows in the active tile.
    </Notice>
  );
}
