import {
  deriveTaskData,
  type FullTask,
  filterByWorkspaceMode,
  filterVisibleTasks,
  limitTasksPerGroup,
  narrowFullTask,
  partitionAndSortTasks,
  type SidebarTask,
  sliceVisibleTasks,
} from "@posthog/core/sidebar/buildSidebarData";
import { groupByRepository } from "@posthog/core/sidebar/groupTasks";
import type {
  SidebarData,
  TaskData,
  TaskGroup,
} from "@posthog/core/sidebar/sidebarData.types";
import { computeSummaryIds } from "@posthog/core/sidebar/summaryIds";
import type { AppView } from "@posthog/ui/router/useAppView";
import { useEffect, useMemo, useRef } from "react";
import { useArchivedTaskIds } from "../archive/useArchivedTaskIds";
import { useFolders } from "../folders/useFolders";
import { useProvisioningStore } from "../provisioning/store";
import { useSuspendedTaskIds } from "../suspension/useSuspendedTaskIds";
import { useSlackTasks, useTaskSummaries, useTasks } from "../tasks/useTasks";
import { useWorkspaces } from "../workspace/useWorkspace";
import { useSidebarStore } from "./sidebarStore";
import { usePinnedTasks } from "./usePinnedTasks";
import { useSidebarSessionMap } from "./useSidebarSessionMap";
import { useTaskViewed } from "./useTaskViewed";

export type { SidebarData, TaskData, TaskGroup };

interface UseSidebarDataProps {
  activeView: AppView;
}

export function useSidebarData({
  activeView,
}: UseSidebarDataProps): SidebarData {
  const showAllUsers = useSidebarStore((state) => state.showAllUsers);
  const showInternal = useSidebarStore((state) => state.showInternal);
  const { data: workspaces, isFetched: isWorkspacesFetched } = useWorkspaces();
  const archivedTaskIds = useArchivedTaskIds();
  const suspendedTaskIds = useSuspendedTaskIds();
  const provisioningTaskIds = useProvisioningStore((s) => s.activeTasks);
  const sessionByTaskId = useSidebarSessionMap();
  const { timestamps } = useTaskViewed();
  const historyVisibleCount = useSidebarStore(
    (state) => state.historyVisibleCount,
  );
  const { pinnedTaskIds } = usePinnedTasks();
  const organizeMode = useSidebarStore((state) => state.organizeMode);
  const sortMode = useSidebarStore((state) => state.sortMode);
  const folderOrder = useSidebarStore((state) => state.folderOrder);
  const taskTypeFilter = useSidebarStore((state) => state.taskTypeFilter);

  const summaryIds = useMemo(
    () =>
      showAllUsers
        ? []
        : computeSummaryIds({
            workspaceIds: workspaces ? Object.keys(workspaces) : [],
            pinnedTaskIds,
            provisioningTaskIds,
            archivedTaskIds,
          }),
    [
      showAllUsers,
      workspaces,
      pinnedTaskIds,
      provisioningTaskIds,
      archivedTaskIds,
    ],
  );

  const { data: summaryTasks = [], isLoading: isSummariesLoading } =
    useTaskSummaries(summaryIds, { enabled: !showAllUsers });
  const { data: fullTasks = [], isLoading: isTasksLoading } = useTasks(
    { showAllUsers, showInternal },
    { enabled: showAllUsers },
  );
  const { data: slackTasks = [] } = useSlackTasks({
    enabled: !showAllUsers,
    showInternal,
  });
  const slackTaskIds = useMemo(
    () => new Set(slackTasks.map((t) => t.id)),
    [slackTasks],
  );
  const slackThreadUrlByTaskId = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of slackTasks) {
      const url = t.latest_run?.state?.slack_thread_url;
      if (typeof url === "string") map.set(t.id, url);
    }
    return map;
  }, [slackTasks]);

  const rawTasks = useMemo<SidebarTask[]>(
    () =>
      showAllUsers
        ? fullTasks.map((t) => narrowFullTask(t as FullTask))
        : (summaryTasks as SidebarTask[]),
    [showAllUsers, summaryTasks, fullTasks],
  );

  const isPrimaryLoading = showAllUsers ? isTasksLoading : isSummariesLoading;
  const isLoading = isPrimaryLoading || !isWorkspacesFetched;

  const workspaceIds = useMemo(
    () => new Set(workspaces ? Object.keys(workspaces) : []),
    [workspaces],
  );

  const allTasks = useMemo(
    () =>
      filterVisibleTasks(rawTasks, {
        archivedIds: archivedTaskIds,
        workspaceIds,
        provisioningIds: provisioningTaskIds,
        showAllUsers,
        showInternal,
      }),
    [
      rawTasks,
      archivedTaskIds,
      workspaceIds,
      showAllUsers,
      showInternal,
      provisioningTaskIds,
    ],
  );

  const isHomeActive =
    activeView.type === "task-input" || activeView.type === "task-pending";
  const isInboxActive = activeView.type === "inbox";
  const isAgentsActive = activeView.type === "agents";
  const isCommandCenterActive = activeView.type === "command-center";
  const isSkillsActive = activeView.type === "skills";
  const isMcpServersActive = activeView.type === "mcp-servers";

  const activeTaskId =
    activeView.type === "task-detail" ? (activeView.taskId ?? null) : null;

  const taskData = useMemo(
    () =>
      allTasks.map((task) =>
        deriveTaskData(task, {
          session: sessionByTaskId.get(task.id),
          workspace: workspaces?.[task.id],
          timestamp: timestamps[task.id],
          pinnedIds: pinnedTaskIds,
          suspendedIds: suspendedTaskIds,
          slackTaskIds,
          slackThreadUrlByTaskId,
        }),
      ),
    [
      allTasks,
      timestamps,
      pinnedTaskIds,
      suspendedTaskIds,
      sessionByTaskId,
      workspaces,
      slackTaskIds,
      slackThreadUrlByTaskId,
    ],
  );

  const filteredTaskData = useMemo(
    () => filterByWorkspaceMode(taskData, taskTypeFilter),
    [taskData, taskTypeFilter],
  );

  const { pinnedTasks, sortedUnpinnedTasks, totalCount } = useMemo(
    () => partitionAndSortTasks(filteredTaskData, sortMode),
    [filteredTaskData, sortMode],
  );

  const { flatTasks, hasMore: flatHasMore } = useMemo(
    () => sliceVisibleTasks(sortedUnpinnedTasks, historyVisibleCount),
    [sortedUnpinnedTasks, historyVisibleCount],
  );

  const { folders } = useFolders();

  // Group the full task set (grouping is cheap, pure JS), then cap each group
  // so "by-project" mode never mounts thousands of rows for a busy project.
  const { groups: groupedTasks, hasMore: groupedHasMore } = useMemo(
    () =>
      limitTasksPerGroup(
        groupByRepository(
          sortedUnpinnedTasks,
          folderOrder,
          organizeMode === "by-project" ? folders : [],
        ),
        historyVisibleCount,
      ),
    [
      sortedUnpinnedTasks,
      folderOrder,
      folders,
      organizeMode,
      historyVisibleCount,
    ],
  );

  const hasMore = organizeMode === "by-project" ? groupedHasMore : flatHasMore;

  const groupIdsRef = useRef<string[]>([]);
  useEffect(() => {
    if (groupedTasks.length === 0) return;
    const groupIds = groupedTasks.map((g) => g.id);
    const prev = groupIdsRef.current;
    if (
      groupIds.length === prev.length &&
      groupIds.every((id, i) => id === prev[i])
    ) {
      return;
    }
    groupIdsRef.current = groupIds;
    useSidebarStore.getState().syncFolderOrder(groupIds);
  }, [groupedTasks]);

  return {
    isHomeActive,
    isInboxActive,
    isAgentsActive,
    isCommandCenterActive,
    isSkillsActive,
    isMcpServersActive,
    isLoading,
    activeTaskId,
    pinnedTasks,
    flatTasks,
    groupedTasks,
    totalCount,
    hasMore,
  };
}
