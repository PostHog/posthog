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
import { memo } from "react";
import { TileRouter } from "./TileRouter";

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

function TileTabContentView({
  tab,
  onActivate,
}: {
  tab: BrowserTab;
  onActivate: (tab: BrowserTab) => void;
}) {
  if (tab.taskId) return <TiledTask taskId={tab.taskId} />;
  if (tab.dashboardId)
    return <WebsiteDashboard dashboardId={tab.dashboardId} />;
  if (tab.href) return <TileRouter key={tab.id} tab={tab} href={tab.href} />;
  return (
    <Notice action={{ label: "Show this tab", onClick: () => onActivate(tab) }}>
      This page only shows in the active tile.
    </Notice>
  );
}

function sameContent(a: BrowserTab, b: BrowserTab): boolean {
  return (
    a.id === b.id &&
    a.href === b.href &&
    a.taskId === b.taskId &&
    a.dashboardId === b.dashboardId
  );
}

export const TileTabContent = memo(
  TileTabContentView,
  (prev, next) =>
    sameContent(prev.tab, next.tab) && prev.onActivate === next.onActivate,
);
