import { findGroupFolder } from "@posthog/core/sidebar/groupTasks";
import {
  computeOrderedVisibleTaskIds,
  computePriorTaskIds,
  formatArchiveResult,
  formatBulkResult,
} from "@posthog/core/sidebar/selection";
import { isTaskActivelyRunning } from "@posthog/core/sidebar/taskRunning";
import { resolveBulkTaskContextMenuIntent } from "@posthog/core/tasks/contextMenuActions";
import { useHostTRPCClient } from "@posthog/host-router/react";
import type { Task, UserBasic } from "@posthog/shared/types";
import {
  archiveTasksImperative,
  useArchiveCacheKeys,
  useArchiveTask,
} from "@posthog/ui/features/archive/useArchiveTask";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { placeTaskInCommandCenter } from "@posthog/ui/features/command-center/placeTaskInCommandCenter";
import { useExternalAppAction } from "@posthog/ui/features/external-apps/useExternalAppAction";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { StopCloudRunDialog } from "@posthog/ui/features/sessions/components/StopCloudRunDialog";
import { useArchivingTasksStore } from "@posthog/ui/features/sidebar/archivingTasksStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { useBulkArchiveConfirm } from "@posthog/ui/features/sidebar/useBulkArchiveConfirm";
import { useClearSelectionOnEscape } from "@posthog/ui/features/sidebar/useClearSelectionOnEscape";
import { useMarqueeSelection } from "@posthog/ui/features/sidebar/useMarqueeSelection";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useSidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import { useSidebarData } from "@posthog/ui/features/sidebar/useSidebarData";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { HandoffTaskDialog } from "@posthog/ui/features/task-detail/components/HandoffTaskDialog";
import { useTaskContextMenu } from "@posthog/ui/features/tasks/useTaskContextMenu";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useWorkspaces } from "@posthog/ui/features/workspace/useWorkspace";
import { DotsCircleSpinner } from "@posthog/ui/primitives/DotsCircleSpinner";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToTaskDetail } from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { logger } from "@posthog/ui/shell/logger";
import { Box, Flex } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRunningTaskDialog } from "./ArchiveRunningTaskDialog";
import { MarqueeOverlay } from "./MarqueeOverlay";
import { SidebarBulkActionBar } from "./SidebarBulkActionBar";
import { SidebarItem } from "./SidebarItem";
import { TaskListView } from "./TaskListView";

const log = logger.scope("sidebar-menu");

function creatorName(createdBy: UserBasic | null | undefined): string | null {
  if (!createdBy) return null;
  const name = [createdBy.first_name, createdBy.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
  return name || createdBy.email || null;
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
  const authStatus = useAuthStateValue((s) => s.status);
  const currentUser = useCurrentUser();
  const { archiveTask } = useArchiveTask();
  const { renameTask } = useRenameTask();
  const { togglePin, setPinnedMany } = usePinnedTasks();

  const sidebarData = useSidebarData({
    activeView: view,
  });

  const taskMap = useMemo(
    () => new Map<string, Task>(allTasks.map((task) => [task.id, task])),
    [allTasks],
  );
  const creatorNameByTaskId = useMemo(() => {
    const names = new Map<string, string>();
    for (const task of allTasks) {
      const name = creatorName(task.created_by);
      if (name) names.set(task.id, name);
    }
    return names;
  }, [allTasks]);

  const commandCenterCells = useCommandCenterStore((s) => s.cells);

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
  const [handoffTaskId, setHandoffTaskId] = useState<string | null>(null);
  const handoffTask = handoffTaskId ? taskMap.get(handoffTaskId) : undefined;

  useClearSelectionOnEscape();
  const listAnchorRef = useRef<HTMLDivElement | null>(null);
  const marquee = useMarqueeSelection(listAnchorRef);

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
  // Depends on the three list fields rather than `sidebarData` itself, which
  // useSidebarData rebuilds as a fresh object every render.
  const orderedVisibleTaskIds = useMemo(
    () =>
      computeOrderedVisibleTaskIds(
        {
          pinnedTasks: sidebarData.pinnedTasks,
          flatTasks: sidebarData.flatTasks,
          groupedTasks: sidebarData.groupedTasks,
        },
        organizeMode,
        collapsedSections,
      ),
    [
      sidebarData.pinnedTasks,
      sidebarData.flatTasks,
      sidebarData.groupedTasks,
      organizeMode,
      collapsedSections,
    ],
  );

  useEffect(() => {
    pruneSelection(allSidebarTaskIds);
  }, [allSidebarTaskIds, pruneSelection]);

  // A bulk action acts on exactly the rows that are highlighted. The routed
  // task used to be folded in as well, which told you "2 selected" after one
  // cmd-click and archived a session you never picked.
  const activeTaskId = sidebarData.activeTaskId;

  const bulkActions = useSidebarBulkActions(selectedTaskIds, allSidebarTasks);
  const bulkArchiveConfirm = useBulkArchiveConfirm(bulkActions);

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
    async (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const allPinned = bulkActions.pinDirection === "unpin";
      try {
        const result =
          await hostClient.contextMenu.showBulkTaskContextMenu.mutate({
            taskCount: bulkActions.selectedCount,
            allPinned,
            runningCount: bulkActions.runningCount,
            stopsCloudSandbox: bulkActions.stopsCloudSandbox,
            channels: bulkActions.channels.map(
              ({ id, name, channelType, starred }) => ({
                id,
                name,
                channelType,
                starred,
              }),
            ),
          });
        if (!result.action) return;

        const intent = resolveBulkTaskContextMenuIntent(result.action, {
          allPinned,
        });
        switch (intent.type) {
          // The native menu confirmed already, so don't also open the dialog.
          case "archive":
            await bulkActions.archiveSelected();
            break;
          case "pin":
          case "unpin":
            await bulkActions.pinSelected();
            break;
          case "add-to-command-center":
            bulkActions.addSelectedToCommandCenter();
            break;
          case "file-to-channel":
            await bulkActions.fileSelectedTo(intent.channelId);
            break;
        }
      } catch (error) {
        log.error("Failed to show bulk context menu", error);
      }
    },
    [bulkActions, hostClient],
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

    // Bulk menu when 2+ rows are selected and the right-clicked row is one of
    // them. A right-click outside the selection clears it first, so the row menu
    // that follows is about the row under the pointer — the same rule the space
    // sidebar applies in ChannelSidebar.
    if (selectedTaskIds.includes(taskId)) {
      if (selectedTaskIds.length > 1) {
        handleBulkContextMenu(e);
        return;
      }
    } else if (selectedTaskIds.length > 0) {
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

      // The menu mirrors the header's rule: only the owner sees Hand off.
      // Read through the full task map: the sidebar's summary rows don't
      // always carry `created_by`.
      const canHandoff =
        authStatus === "authenticated" &&
        currentUser.data?.id != null &&
        taskMap.get(taskId)?.created_by?.id === currentUser.data.id;

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
        hasEmptyCommandCenterCell: true,
        canHandoff,
        onHandoff: () => setHandoffTaskId(task.id),
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
          placeTaskInCommandCenter(taskId, task.title);
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

  // One request for the batch rather than a toggle per row: pinning is a scoped
  // mutation, so a row-at-a-time batch waits out a round trip for each one.
  const handleTasksSetPinned = useCallback(
    async (taskIds: string[], pinned: boolean) => {
      const archiving = useArchivingTasksStore.getState();
      const eligible = taskIds.filter((id) => !archiving.isArchiving(id));
      if (eligible.length === 0) return;
      try {
        // setPinnedMany settles every request itself and reports the failures
        // in `failed` rather than rejecting, so surface them the same way the
        // bulk action bar does — a bare .catch() never sees a partial failure.
        const { succeeded, failed } = await setPinnedMany(eligible, pinned);
        if (failed.length > 0) {
          const { message } = formatBulkResult(pinned ? "pinned" : "unpinned", {
            succeeded: succeeded.length,
            failed: failed.length,
          });
          toast.error(message);
        }
      } catch (error) {
        log.error("Failed to set pinned sessions", error);
        toast.error(`Couldn't ${pinned ? "pin" : "unpin"} the sessions`);
      }
    },
    [setPinnedMany],
  );

  const handleArchivePrior = useCallback(
    async (taskId: string) => {
      const priorTaskIds = computePriorTaskIds(allSidebarTasks, taskId);
      if (priorTaskIds.length === 0) {
        toast.info("No older tasks to archive");
        return;
      }

      const result = formatArchiveResult(
        await archiveTasksImperative(
          priorTaskIds,
          queryClient,
          archiveCacheKeys,
        ),
      );
      if (result.kind === "success") toast.success(result.message);
      else toast.error(result.message);
    },
    [allSidebarTasks, queryClient, archiveCacheKeys],
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
      ref={listAnchorRef}
    >
      <MarqueeOverlay rect={marquee} />
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        {/* Full height, so the space under the last row still belongs to the
            list. That space is where an unpin drag is released. */}
        <Flex direction="column" className="min-h-full gap-px px-2 pb-2">
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
              selectedTaskIds={selectedTaskIds}
              onTaskClick={handleTaskClick}
              onTaskDoubleClick={handleTaskDoubleClick}
              onTaskContextMenu={handleTaskContextMenu}
              onTaskArchive={handleTaskArchive}
              onTaskTogglePin={handleTaskTogglePin}
              onTasksSetPinned={handleTasksSetPinned}
              onTaskEditSubmit={handleTaskEditSubmit}
              onTaskEditCancel={handleTaskEditCancel}
              onGroupContextMenu={handleGroupContextMenu}
              creatorNameByTaskId={creatorNameByTaskId}
              hasMore={sidebarData.hasMore}
            />
          )}
        </Flex>
      </div>

      {/* A sticky footer rather than an overlay: the list shrinks instead of
          having its bottom rows — where a shift-click range usually ends —
          covered up. */}
      <SidebarBulkActionBar
        actions={bulkActions}
        onClearSelection={clearSelection}
        onArchive={bulkArchiveConfirm.requestArchive}
      />
      {bulkArchiveConfirm.dialog}

      <ArchiveRunningTaskDialog
        open={archiveConfirm !== null}
        taskTitle={archiveConfirm?.taskTitle ?? ""}
        stopsCloudSandbox={Boolean(archiveConfirm?.stopsCloudSandbox)}
        onConfirm={handleConfirmArchive}
        onCancel={() => setArchiveConfirm(null)}
      />
      {handoffTask ? (
        <HandoffTaskDialog
          task={handoffTask}
          open
          onOpenChange={(open) => {
            if (!open) setHandoffTaskId(null);
          }}
        />
      ) : null}
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
