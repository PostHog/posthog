// Full-task polls are heavy (~630KB per response at 100 tasks — descriptions
// and latest_run blobs included), and idle-poll churn was the app's largest
// memory/CPU drain. The sidebar's primary freshness comes from the slim
// summaries poll; full-task consumers are lookups where a minute of staleness
// is invisible.
export const TASK_LIST_POLL_INTERVAL_MS = 60_000;
export const TASK_LIST_FALLBACK_POLL_INTERVAL_MS = 5 * 60_000;

export interface TaskListHookFilters {
  repository?: string;
  showAllUsers?: boolean;
  showInternal?: boolean;
}

export function taskListRefetchIntervalMs(
  filters: TaskListHookFilters | undefined,
  channelsWorldActive: boolean,
): number {
  const plainMineList =
    !filters?.repository && !filters?.showAllUsers && !filters?.showInternal;
  return plainMineList && channelsWorldActive
    ? TASK_LIST_FALLBACK_POLL_INTERVAL_MS
    : TASK_LIST_POLL_INTERVAL_MS;
}
