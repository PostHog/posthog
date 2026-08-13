export const TASK_LIST_POLL_INTERVAL_MS = 60_000;
export const TASK_LIST_FALLBACK_POLL_INTERVAL_MS = 5 * 60_000;

export interface TaskListHookFilters {
  repository?: string;
  showAllUsers?: boolean;
  showInternal?: boolean;
}

export function taskListRefetchIntervalMs(
  filters: TaskListHookFilters | undefined,
  allUsersListMounted: boolean,
): number {
  const plainMineList =
    !filters?.repository && !filters?.showAllUsers && !filters?.showInternal;
  return plainMineList && allUsersListMounted
    ? TASK_LIST_FALLBACK_POLL_INTERVAL_MS
    : TASK_LIST_POLL_INTERVAL_MS;
}
