import { findGroupFolder } from "@posthog/core/sidebar/groupTasks";
import { isTaskActivelyRunning } from "@posthog/core/sidebar/taskRunning";
import { useHostTRPCClient } from "@posthog/host-router/react";
import type { Task } from "@posthog/shared/types";
import {
  archiveTasksImperative,
  useArchiveCacheKeys,
  useArchiveTask,
} from "@posthog/ui/features/archive/useArchiveTask";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { useExternalAppAction } from "@posthog/ui/features/external-apps/useExternalAppAction";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { StopCloudRunDialog } from "@posthog/ui/features/sessions/components/StopCloudRunDialog";
import { useArchivingTasksStore } from "@posthog/ui/features/sidebar/archivingTasksStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useSidebarData } from "@posthog/ui/features/sidebar/useSidebarData";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useTaskContextMenu } from "@posthog/ui/features/tasks/useTaskContextMenu";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useWorkspaces } from "@posthog/ui/features/workspace/useWorkspace";
import { DotsCircleSpinner } from "@posthog/ui/primitives/DotsCircleSpinner";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToCommandCenter,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { logger } from "@posthog/ui/shell/logger";
import { Box, Flex } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRunningTaskDialog } from "./ArchiveRunningTaskDialog";
import { SidebarItem } from "./SidebarItem";
import { TaskListView } from "./TaskListView";
import { TasksHeader } from "./TasksHeader";

const log = logger.scope("sidebar-menu");

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function SidebarMenuComponent() {
  const hostClient = useHostTRPCClient();
  const archiveCacheKeys = useArchiveCacheKeys();
  const view = useAppView();

  // Must mirror useSidebarData's filters so taskMap covers every rendered
  // task — otherwise handleTaskClick silently bails for tasks not in the map.
  const showAllUsers = useSidebarStore((s) => s.showAllUsers);
  const showInternal = useSidebarStore((s) => s.showInternal);
  const { data: allTasks = [] } = useTasks({ showAllUsers, showInternal });

  const { data: workspaces = {} } = useWorkspaces();
  const { markAsViewed } = useTaskViewed();

  const { folders, removeFolder } = useFolders();

  const openExternalApp = useExternalAppAction();

  const { showContextMenu, editingTaskId, setEditingTaskId } =
    useTaskContextMenu();
  const { archiveTask } = useArchiveTask();
  const { renameTask } = useRenameTask();
  const { togglePin } = usePinnedTasks();

  const sidebarData = useSidebarData({
    activeView: view,
  });

  const taskMap = useMemo(
    () => new Map<string, Task>(allTasks.map((task) => [task.id, task])),
    [allTasks],
  );

  const commandCenterCells = useCommandCenterStore((s) => s.cells);
  const assignTaskToCommandCenter = useCommandCenterStore((s) => s.assignTask);

  const previousTaskIdRef = useRef<string | null>(null);

  useEffect(() => {
    const currentTaskId =
      view.type === "task-detail" && view.taskId ? view.taskId : null;

    if (
      previousTaskIdRef.current &&
      previousTaskIdRef.current !== currentTaskId
    ) {
      markAsViewed(previousTaskIdRef.current);
    }

    if (currentTaskId) {
      markAsViewed(currentTaskId);
    }

    previousTaskIdRef.current = currentTaskId;
  }, [view, markAsViewed]);

  const queryClient = useQueryClient();

  const [archiveConfirm, setArchiveConfirm] = useState<{
    taskId: string;
    taskTitle: string;
    stopsCloudSandbox: boolean;
  } | null>(null);
  const [stopConfirm, setStopConfirm] = useState<{
    taskId: string;
    taskTitle: string;
    runId?: string;
  } | null>(null);

  // Escape clears any bulk task selection (moved here from the retired
  // MainSidebar so it survives with the task list in the unified sidebar).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (isEditableTarget(e.target)) return;
      const { selectedTaskIds, clearSelection } =
        useTaskSelectionStore.getState();
      if (selectedTaskIds.length === 0) return;
      clearSelection();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const selectedTaskIds = useTaskSelectionStore((s) => s.selectedTaskIds);
  const toggleTaskSelection = useTaskSelectionStore(
    (s) => s.toggleTaskSelection,
  );
  const selectRange = useTaskSelectionStore((s) => s.selectRange);
  const clearSelection = useTaskSelectionStore((s) => s.clearSelection);
  const pruneSelection = useTaskSelectionStore((s) => s.pruneSelection);

  const organizeMode = useSidebarStore((s) => s.organizeMode);
  const collapsedSections = useSidebarStore((s) => s.collapsedSections);

  const allSidebarTasks = useMemo(
    () => [...sidebarData.pinnedTasks, ...sidebarData.flatTasks],
    [sidebarData.pinnedTasks, sidebarData.flatTasks],
  );

  const allSidebarTaskIds = useMemo(
    () => allSidebarTasks.map((t) => t.id),
    [allSidebarTasks],
  );

  // Ordered list of currently visible task IDs in display order. Used as the
  // index for shift-click range selection so it matches what the user sees —
  // in by-project mode the chronological flat order would span across project
  // groups and pull in unrelated tasks.
  const orderedVisibleTaskIds = useMemo(() => {
    const ids: string[] = sidebarData.pinnedTasks.map((t) => t.id);
    if (organizeMode === "by-project") {
      for (const group of sidebarData.groupedTasks) {
        if (collapsedSections.has(group.id)) continue;
        for (const t of group.tasks) ids.push(t.id);
      }
    } else {
      for (const t of sidebarData.flatTasks) ids.push(t.id);
    }
    return ids;
  }, [
    sidebarData.pinnedTasks,
    sidebarData.flatTasks,
    sidebarData.groupedTasks,
    organizeMode,
    collapsedSections,
  ]);

  useEffect(() => {
    pruneSelection(allSidebarTaskIds);
  }, [allSidebarTaskIds, pruneSelection]);

  // The active (routed) task is implicitly part of any bulk selection — the
  // user expects to see and act on it together with cmd/shift-clicked tasks.
  const activeTaskId = sidebarData.activeTaskId;
  const effectiveBulkIds = useMemo(() => {
    if (selectedTaskIds.length === 0) return [];
    if (!activeTaskId) return selectedTaskIds;
    if (selectedTaskIds.includes(activeTaskId)) return selectedTaskIds;
    return [activeTaskId, ...selectedTaskIds];
  }, [activeTaskId, selectedTaskIds]);

  const handleTaskClick = (taskId: string, e: React.MouseEvent) => {
    // Ignore clicks on a row that's mid-archive.
    if (useArchivingTasksStore.getState().isArchiving(taskId)) {
      e.preventDefault();
      return;
    }
    if (e.shiftKey) {
      e.preventDefault();
      selectRange(taskId, orderedVisibleTaskIds, activeTaskId);
      return;
    }
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      toggleTaskSelection(taskId);
      return;
    }

    clearSelection();
    const task = taskMap.get(taskId);
    if (task) {
      void openTask(task);
    } else {
      // Sidebar rows come from the summaries path, which can include tasks the
      // full-list query (taskMap) doesn't carry. Don't silently bail — navigate
      // by id; the task-detail route resolves the task from its own query.
      navigateToTaskDetail(taskId);
    }
  };

  const handleBulkContextMenu = useCallback(
    async (e: React.MouseEvent, taskIds: string[]) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        const result =
          await hostClient.contextMenu.showBulkTaskContextMenu.mutate({
            taskCount: taskIds.length,
          });
        if (!result.action) return;
        if (result.action.type === "archive") {
          const { archived, failed } = await archiveTasksImperative(
            taskIds,
            queryClient,
            archiveCacheKeys,
          );
          clearSelection();
          if (failed === 0) {
            toast.success(
              `${archived} ${archived === 1 ? "task" : "tasks"} archived`,
            );
          } else {
            toast.error(`${archived} archived, ${failed} failed`);
          }
        }
      } catch (error) {
        log.error("Failed to show bulk context menu", error);
      }
    },
    [hostClient, queryClient, clearSelection, archiveCacheKeys],
  );

  const handleGroupContextMenu = useCallback(
    async (groupId: string, e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const folder = findGroupFolder(folders, groupId);
      if (!folder) return;
      try {
        const result =
          await hostClient.contextMenu.showFolderContextMenu.mutate({
            folderName: folder.name,
            folderPath: folder.path,
          });
        if (result.action?.type === "remove") {
          await removeFolder(folder.id);
        } else if (result.action?.type === "external-app") {
          await openExternalApp(
            result.action.action,
            folder.path,
            folder.name,
            { workspace: null },
          );
        }
      } catch (error) {
        log.error("Failed to show folder context menu", error);
        toast.error("Couldn't perform folder action");
      }
    },
    [folders, removeFolder, hostClient, openExternalApp],
  );

  const handleTaskContextMenu = (
    taskId: string,
    e: React.MouseEvent,
    isPinned: boolean,
  ) => {
    // Right-clicking a row that's mid-archive is a no-op.
    if (useArchivingTasksStore.getState().isArchiving(taskId)) {
      e.preventDefault();
      return;
    }

    // Bulk menu when 2+ tasks are in the effective selection (active + cmd/shift-clicked)
    // and the right-clicked task is one of them. Otherwise clear and fall through.
    if (effectiveBulkIds.length > 1) {
      if (effectiveBulkIds.includes(taskId)) {
        handleBulkContextMenu(e, effectiveBulkIds);
        return;
      }
      clearSelection();
    }

    const taskData = allSidebarTasks.find((t) => t.id === taskId);
    const task = taskMap.get(taskId) ?? taskData;
    if (task) {
      const runId = taskMap.get(taskId)?.latest_run?.id;
      const workspace = workspaces[taskId];
      const isInCommandCenter = commandCenterCells.some(
        (id) => id === taskId && taskMap.has(id),
      );
      const hasEmptyCommandCenterCell = commandCenterCells.some(
        (id) => id == null || !taskMap.has(id),
      );

      showContextMenu(task, e, {
        worktreePath: workspace?.worktreePath ?? undefined,
        folderPath: workspace?.folderPath ?? undefined,
        isPinned,
        isSuspended: taskData?.isSuspended,
        canStop:
          taskData?.taskRunEnvironment === "cloud" &&
          isTaskActivelyRunning(taskData),
        runId,
        isInCommandCenter,
        hasEmptyCommandCenterCell,
        onTogglePin: () => handleTaskTogglePin(taskId),
        onStop: (stopTaskId, taskTitle, stopRunId) =>
          setStopConfirm({
            taskId: stopTaskId,
            taskTitle,
            runId: stopRunId,
          }),
        onArchive: handleTaskArchive,
        onArchivePrior: handleArchivePrior,
        onAddToCommandCenter: () => {
          const cells = useCommandCenterStore.getState().cells;
          const idx = cells.findIndex((id) => id == null || !taskMap.has(id));
          if (idx !== -1) {
            assignTaskToCommandCenter(idx, taskId);
            navigateToCommandCenter();
          } else {
            toast.info("Command center is full");
          }
        },
      });
    }
  };

  // Runs the archive while marking the row as in-flight, so its sidebar entry
  // shows a spinner and ignores clicks/pins/right-clicks until it resolves.
  // Guards against repeated clicks: a second call while archiving is a no-op.
  const runArchive = useCallback(
    async (taskId: string) => {
      const store = useArchivingTasksStore.getState();
      if (store.isArchiving(taskId)) {
        return {
          success: false,
          error: new Error("Task is already archiving"),
        };
      }
      store.startArchiving(taskId);
      try {
        await archiveTask({ taskId });
        return { success: true as const };
      } catch (error) {
        log.error("Failed to archive task", error);
        toast.error("Failed to archive task");
        return { success: false as const, error };
      } finally {
        useArchivingTasksStore.getState().stopArchiving(taskId);
      }
    },
    [archiveTask],
  );

  const handleTaskArchive = useCallback(
    (taskId: string) => {
      if (useArchivingTasksStore.getState().isArchiving(taskId)) return;
      const task = allSidebarTasks.find((t) => t.id === taskId);
      if (task && isTaskActivelyRunning(task)) {
        setArchiveConfirm({
          taskId,
          taskTitle: task.title,
          stopsCloudSandbox: task.taskRunEnvironment === "cloud",
        });
        return;
      }
      void runArchive(taskId);
    },
    [allSidebarTasks, runArchive],
  );

  const handleConfirmArchive = useCallback(async () => {
    if (!archiveConfirm) return;
    const { taskId } = archiveConfirm;
    const result = await runArchive(taskId);
    if (!result.success) {
      throw result.error instanceof Error
        ? result.error
        : new Error("Couldn't archive the task. Try again in a moment.");
    }
    setArchiveConfirm(null);
  }, [archiveConfirm, runArchive]);

  const handleTaskTogglePin = useCallback(
    (taskId: string) => {
      // Pinning/unpinning a row that's mid-archive is a no-op.
      if (useArchivingTasksStore.getState().isArchiving(taskId)) return;
      togglePin(taskId);
    },
    [togglePin],
  );

  const handleArchivePrior = useCallback(
    async (taskId: string) => {
      const allVisible = [...sidebarData.pinnedTasks, ...sidebarData.flatTasks];
      const clickedTask = allVisible.find((t) => t.id === taskId);
      if (!clickedTask) return;

      const threshold = clickedTask.lastActivityAt;
      const priorTaskIds = allVisible
        .filter((t) => t.id !== taskId && t.lastActivityAt < threshold)
        .map((t) => t.id);

      if (priorTaskIds.length === 0) {
        toast.info("No older tasks to archive");
        return;
      }

      const { archived, failed } = await archiveTasksImperative(
        priorTaskIds,
        queryClient,
        archiveCacheKeys,
      );

      if (failed === 0) {
        toast.success(
          `${archived} ${archived === 1 ? "task" : "tasks"} archived`,
        );
      } else {
        toast.error(`${archived} archived, ${failed} failed`);
      }
    },
    [
      sidebarData.pinnedTasks,
      sidebarData.flatTasks,
      queryClient,
      archiveCacheKeys,
    ],
  );
  const handleTaskDoubleClick = useCallback(
    (taskId: string) => {
      setEditingTaskId(taskId);
    },
    [setEditingTaskId],
  );

  const handleTaskEditSubmit = useCallback(
    async (taskId: string, currentTitle: string, newTitle: string) => {
      setEditingTaskId(null);

      try {
        await renameTask({
          taskId,
          currentTitle,
          newTitle,
        });
      } catch (error) {
        log.error("Failed to rename task", error);
      }
    },
    [renameTask, setEditingTaskId],
  );

  const handleTaskEditCancel = useCallback(() => {
    setEditingTaskId(null);
  }, [setEditingTaskId]);

  return (
    <Box
      height="100%"
      position="relative"
      id="side-bar-menu"
      className="flex min-h-0 flex-col"
    >
      <TasksHeader />

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <Flex direction="column" className="gap-px px-2 pb-2">
          {sidebarData.isLoading ? (
            <SidebarItem
              depth={0}
              icon={<DotsCircleSpinner size={12} className="text-gray-10" />}
              label="Loading tasks..."
              disabled
            />
          ) : (
            <TaskListView
              pinnedTasks={sidebarData.pinnedTasks}
              flatTasks={sidebarData.flatTasks}
              groupedTasks={sidebarData.groupedTasks}
              activeTaskId={sidebarData.activeTaskId}
              editingTaskId={editingTaskId}
              selectedTaskIds={effectiveBulkIds}
              onTaskClick={handleTaskClick}
              onTaskDoubleClick={handleTaskDoubleClick}
              onTaskContextMenu={handleTaskContextMenu}
              onTaskArchive={handleTaskArchive}
              onTaskTogglePin={handleTaskTogglePin}
              onTaskEditSubmit={handleTaskEditSubmit}
              onTaskEditCancel={handleTaskEditCancel}
              onGroupContextMenu={handleGroupContextMenu}
              hasMore={sidebarData.hasMore}
            />
          )}
        </Flex>
      </div>

      <ArchiveRunningTaskDialog
        open={archiveConfirm !== null}
        taskTitle={archiveConfirm?.taskTitle ?? ""}
        stopsCloudSandbox={Boolean(archiveConfirm?.stopsCloudSandbox)}
        onConfirm={handleConfirmArchive}
        onCancel={() => setArchiveConfirm(null)}
      />
      {stopConfirm ? (
        <StopCloudRunDialog
          open
          taskId={stopConfirm.taskId}
          runId={stopConfirm.runId}
          title={`Stop "${stopConfirm.taskTitle}"?`}
          buttonLabel="Stop task"
          onOpenChange={(open) => {
            if (!open) setStopConfirm(null);
          }}
          onStopped={() => toast.success("Stop requested")}
        />
      ) : null}
    </Box>
  );
}

export const SidebarMenu = memo(SidebarMenuComponent);
