export const TASK_LIST_POLL_INTERVAL_MS = 60_000;
export const TASK_LIST_FALLBACK_POLL_INTERVAL_MS = 5 * 60_000;

export interface TaskListHookFilters {
  repository?: string;
  showAllUsers?: boolean;
  showInternal?: boolean;
}

function isUnfiltered(filters: TaskListHookFilters | undefined): boolean {
  return !filters?.repository && !filters?.showInternal;
}

export function isAllUsersTaskList(
  filters: TaskListHookFilters | undefined,
): boolean {
  return Boolean(filters?.showAllUsers) && isUnfiltered(filters);
}

export function isPlainMineTaskList(
  filters: TaskListHookFilters | undefined,
): boolean {
  return !filters?.showAllUsers && isUnfiltered(filters);
}

export function taskListRefetchIntervalMs(
  filters: TaskListHookFilters | undefined,
  allUsersListMounted: boolean,
): number {
  return isPlainMineTaskList(filters) && allUsersListMounted
    ? TASK_LIST_FALLBACK_POLL_INTERVAL_MS
    : TASK_LIST_POLL_INTERVAL_MS;
}
