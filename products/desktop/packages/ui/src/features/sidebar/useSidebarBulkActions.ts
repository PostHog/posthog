import {
  type BulkResultKind,
  computeBulkPinDirection,
  formatBulkResult,
  sessionsLabel,
} from "@posthog/core/sidebar/selection";
import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { isTaskActivelyRunning } from "@posthog/core/sidebar/taskRunning";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import {
  archiveTasksImperative,
  useArchiveCacheKeys,
} from "@posthog/ui/features/archive/useArchiveTask";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { placeTasksInCommandCenter } from "@posthog/ui/features/command-center/placeTaskInCommandCenter";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useArchivingTasksStore } from "@posthog/ui/features/sidebar/archivingTasksStore";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useLiveTaskIds } from "@posthog/ui/features/tasks/useLiveTaskIds";
import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

const log = logger.scope("sidebar-bulk-actions");

/** Stable empty list, so a gated-off channels array keeps a steady identity. */
const EMPTY_CHANNELS: Channel[] = [];

/** Clause after "Disabled because …" (see `@posthog/ui/primitives/Button`). */
const NO_SELECTION = "you haven't selected any sessions";
const NO_CHANNELS = "this project has no channels to file to";

export interface SidebarBulkActions {
  selectedCount: number;
  /** How many of the selection are still running, so archiving would stop them. */
  runningCount: number;
  stopsCloudSandbox: boolean;
  pinDirection: "pin" | "unpin";
  pinLabel: string;
  channels: Channel[];
  archiveSelected: () => Promise<void>;
  pinSelected: () => Promise<void>;
  addSelectedToCommandCenter: () => void;
  fileSelectedTo: (channelId: string) => Promise<void>;
  archiveDisabledReason: string | null;
  pinDisabledReason: string | null;
  commandCenterDisabledReason: string | null;
  fileDisabledReason: string | null;
  isArchiving: boolean;
  isPinning: boolean;
  isFiling: boolean;
}

/**
 * What a bulk action needs to know about a session beyond its id: only enough
 * to say whether archiving it would stop something. Narrower than `TaskData` so
 * both session lists can feed this without one shape dictating the other.
 */
export type BulkSessionInfo = Pick<
  TaskData,
  "id" | "isGenerating" | "taskRunEnvironment" | "taskRunStatus"
>;

/**
 * The four bulk actions offered over a multi-session selection, shared by the
 * action bar and the bulk right-click menu so the two can't drift apart.
 */
export function useSidebarBulkActions(
  taskIds: string[],
  tasks: BulkSessionInfo[],
): SidebarBulkActions {
  const queryClient = useQueryClient();
  const archiveCacheKeys = useArchiveCacheKeys();
  const clearSelection = useTaskSelectionStore((s) => s.clearSelection);
  const setSelectedTaskIds = useTaskSelectionStore((s) => s.setSelectedTaskIds);
  const { pinnedTaskIds, setPinnedMany, isSettingPinnedMany } =
    usePinnedTasks();

  // "File to…" is a Project Bluebird feature. `enabled` only stops the fetch, and
  // an ungated surface elsewhere can still have filled the shared cache, so the
  // flag has to gate the list itself rather than just the request.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const { channels: fetchedChannels } = useChannels({
    enabled: bluebirdEnabled,
  });
  const channels = bluebirdEnabled ? fetchedChannels : EMPTY_CHANNELS;
  const { fileTask } = useChannelTaskMutations();

  const liveTaskIds = useLiveTaskIds();

  const [isArchiving, setIsArchiving] = useState(false);
  const [isFiling, setIsFiling] = useState(false);

  const selectedCount = taskIds.length;

  const selectedTasks = useMemo(() => {
    const ids = new Set(taskIds);
    return tasks.filter((task) => ids.has(task.id));
  }, [taskIds, tasks]);

  const runningTasks = useMemo(
    () => selectedTasks.filter(isTaskActivelyRunning),
    [selectedTasks],
  );

  const pinDirection = useMemo(
    () => computeBulkPinDirection(taskIds, pinnedTaskIds),
    [taskIds, pinnedTaskIds],
  );

  const report = useCallback(
    (kind: BulkResultKind, succeeded: number, failed: number) => {
      const result = formatBulkResult(kind, { succeeded, failed });
      if (result.kind === "success") toast.success(result.message);
      else toast.error(result.message);
    },
    [],
  );

  // Full success clears the selection; a partial one narrows it to exactly the
  // failures so the user can retry those.
  const reconcileSelection = useCallback(
    (failedIds: string[]) => {
      if (failedIds.length === 0) clearSelection();
      else setSelectedTaskIds(failedIds);
    },
    [clearSelection, setSelectedTaskIds],
  );

  const archiveSelected = useCallback(async () => {
    if (selectedCount === 0 || isArchiving) return;
    setIsArchiving(true);
    const store = useArchivingTasksStore.getState();
    for (const id of taskIds) store.startArchiving(id);
    try {
      const { archived, failed } = await archiveTasksImperative(
        taskIds,
        queryClient,
        archiveCacheKeys,
      );
      // archiveTasks reports counts, not ids, so a partial failure can't narrow
      // the selection to the stragglers — leave it whole so a retry is one click.
      if (failed === 0) clearSelection();
      report("archived", archived, failed);
    } catch (error) {
      log.error("Failed to archive sessions", error);
      toast.error("Couldn't archive the selected sessions");
    } finally {
      const current = useArchivingTasksStore.getState();
      for (const id of taskIds) current.stopArchiving(id);
      setIsArchiving(false);
    }
  }, [
    archiveCacheKeys,
    clearSelection,
    isArchiving,
    queryClient,
    report,
    selectedCount,
    taskIds,
  ]);

  const pinSelected = useCallback(async () => {
    if (selectedCount === 0) return;
    const pinned = pinDirection === "pin";
    try {
      const { succeeded, failed } = await setPinnedMany(taskIds, pinned);
      reconcileSelection(failed);
      report(pinned ? "pinned" : "unpinned", succeeded.length, failed.length);
    } catch (error) {
      log.error("Failed to pin sessions", error);
      toast.error(`Couldn't ${pinned ? "pin" : "unpin"} the selected sessions`);
    }
  }, [
    pinDirection,
    reconcileSelection,
    report,
    selectedCount,
    setPinnedMany,
    taskIds,
  ]);

  const addSelectedToCommandCenter = useCallback(() => {
    if (selectedCount === 0) return;
    const { placed, overflow, alreadyPresent } = placeTasksInCommandCenter(
      taskIds,
      liveTaskIds,
    );
    // Selection survives an overflow so the sessions that didn't fit can go
    // somewhere else in one more click. Placement reports counts rather than
    // ids, so the whole selection stays rather than narrowing to the leftovers.
    if (overflow > 0) {
      toast.warning(
        `${placed} added to Command Center, ${overflow} didn't fit`,
      );
      return;
    }
    clearSelection();
    // Nothing moved because the whole batch was already tiled — saying "0
    // added" would read as a failure when the grid is exactly as asked.
    if (placed === 0 && alreadyPresent > 0) {
      toast.info(`${sessionsLabel(alreadyPresent)} already in Command Center`);
      return;
    }
    report("added to Command Center", placed, 0);
  }, [clearSelection, liveTaskIds, report, selectedCount, taskIds]);

  const fileSelectedTo = useCallback(
    async (channelId: string) => {
      if (selectedCount === 0 || isFiling) return;
      setIsFiling(true);
      try {
        const results = await Promise.allSettled(
          taskIds.map((taskId) => fileTask(channelId, taskId)),
        );
        const failedIds = taskIds.filter(
          (_, i) => results[i].status === "rejected",
        );
        reconcileSelection(failedIds);
        report("filed", taskIds.length - failedIds.length, failedIds.length);
      } finally {
        setIsFiling(false);
      }
    },
    [fileTask, isFiling, reconcileSelection, report, selectedCount, taskIds],
  );

  // Memoized because SidebarMenu's bulk callbacks depend on this object; a
  // fresh identity per render would defeat every useCallback downstream.
  return useMemo(() => {
    const noSelection = selectedCount === 0 ? NO_SELECTION : null;
    return {
      selectedCount,
      runningCount: runningTasks.length,
      stopsCloudSandbox: runningTasks.some(
        (task) => task.taskRunEnvironment === "cloud",
      ),
      pinDirection,
      pinLabel: `${pinDirection === "pin" ? "Pin" : "Unpin"} ${sessionsLabel(selectedCount)}`,
      channels,
      archiveSelected,
      pinSelected,
      addSelectedToCommandCenter,
      fileSelectedTo,
      archiveDisabledReason: noSelection,
      pinDisabledReason: noSelection,
      commandCenterDisabledReason: noSelection,
      fileDisabledReason:
        noSelection ?? (channels.length === 0 ? NO_CHANNELS : null),
      isArchiving,
      isPinning: isSettingPinnedMany,
      isFiling,
    };
  }, [
    addSelectedToCommandCenter,
    archiveSelected,
    channels,
    fileSelectedTo,
    isArchiving,
    isFiling,
    isSettingPinnedMany,
    pinDirection,
    pinSelected,
    runningTasks,
    selectedCount,
  ]);
}
