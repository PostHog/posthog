// Full-task polls are heavy (~630KB per response at 100 tasks — descriptions
// and latest_run blobs included), and idle-poll churn was the app's largest
// memory/CPU drain. The sidebar's primary freshness comes from the slim
// summaries poll; full-task consumers are lookups where a minute of staleness
// is invisible.
export const TASK_LIST_POLL_INTERVAL_MS = 60_000;
// While the channel list is mounted it already polls the unfiltered org-wide
// task list every TASK_LIST_POLL_INTERVAL_MS for the space badges, and that
// response carries every row the plain created-by-me list would fetch (up to
// the page cap). Polling the "mine" copy just as fast fetches the same tasks
// twice, so it drops to a slow safety net that only covers what the org-wide
// page can miss, with focus refetches and `["tasks"]` invalidations still
// refreshing it on real activity.
export const TASK_LIST_FALLBACK_POLL_INTERVAL_MS = 5 * 60_000;

export interface TaskListHookFilters {
  repository?: string;
  showAllUsers?: boolean;
  showInternal?: boolean;
}

/**
 * The refetch interval for one task-list query. Only the plain
 * created-by-me list slows down while the channels world is active: the
 * repository, internal, and all-users variants fetch rows the badge poll
 * does not duplicate, so they keep the full cadence.
 */
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
