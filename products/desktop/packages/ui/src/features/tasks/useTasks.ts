import { TASK_LIST_MAX_PAGE_SIZE } from "@posthog/api-client/posthog-client";
import type { TaskSummaryDTO } from "@posthog/api-client/task-normalization";
import type { Task } from "@posthog/shared/domain-types";
import { keepPreviousData } from "@tanstack/react-query";
import { useAuthenticatedQuery } from "../../hooks/useAuthenticatedQuery";
import { useMeQuery } from "../auth/useMeQuery";
import { taskKeys } from "./taskKeys";

// Full-task polls are heavy (~630KB per response at 100 tasks — descriptions
// and latest_run blobs included), and idle-poll churn was the app's largest
// memory/CPU drain. The sidebar's primary freshness comes from the slim
// summaries poll; full-task consumers are lookups where a minute of staleness
// is invisible.
const TASK_LIST_POLL_INTERVAL_MS = 60_000;
// Summaries are slim and drive the sidebar's live status — keep them fresh.
const TASK_SUMMARY_POLL_INTERVAL_MS = 30_000;
// A task's slack origin and thread URL are set at creation and never change;
// this poll only decorates rows with slack icons/links, so it mainly needs to
// notice new tasks. Full payloads across all users made this the single
// heaviest poll in the app (~2.2MB per response every 30s).
const SLACK_TASK_POLL_INTERVAL_MS = 5 * 60_000;

export function useTasks(
  filters?: {
    repository?: string;
    showAllUsers?: boolean;
    showInternal?: boolean;
    sources?: readonly string[];
    limit?: number;
    ordering?: "-last_activity_at" | "-created_at";
  },
  options?: {
    enabled?: boolean;
    subscribed?: boolean;
    keepPreviousPage?: boolean;
  },
) {
  const { data: currentUser } = useMeQuery();
  const createdBy = filters?.showAllUsers ? undefined : currentUser?.id;
  const internal = filters?.showInternal ? true : undefined;
  const sources = filters?.sources?.length
    ? [...filters.sources].sort()
    : undefined;

  return useAuthenticatedQuery(
    taskKeys.list({
      repository: filters?.repository,
      createdBy,
      internal,
      sources,
      limit: filters?.limit,
      ordering: filters?.ordering,
    }),
    (client) =>
      client.getTasks({
        repository: filters?.repository,
        createdBy,
        internal,
        sources,
        limit: filters?.limit,
        ordering: filters?.ordering,
        // The sidebar and every other full-list consumer narrow the task before use
        // and never read its description, so ask for the basic payload without it.
        basic: true,
      }) as unknown as Promise<Task[]>,
    {
      enabled: (options?.enabled ?? true) && !!currentUser?.id,
      subscribed: options?.subscribed,
      refetchInterval: TASK_LIST_POLL_INTERVAL_MS,
      placeholderData: options?.keepPreviousPage ? keepPreviousData : undefined,
    },
  );
}

/**
 * Pinned records read every page on each poll, so the poll waits one interval per page. Any pin
 * history then costs about one page request a minute and still refreshes.
 */
export function pinnedRecordsPollInterval(
  pinCount: number | undefined,
): number {
  const pages = Math.max(
    1,
    Math.ceil((pinCount ?? 0) / TASK_LIST_MAX_PAGE_SIZE),
  );
  return pages * TASK_LIST_POLL_INTERVAL_MS;
}

// A pin can be on any task the user can see, also one older than the recent list reaches. The
// server cuts each page at 100 rows, so this reads every page to keep every pin. It polls like the
// other task lists: a pin on another user's task, or from a source the work list hides, has no
// other path to a fresh status. It goes stale as fast as the pin IDs in usePinnedTasks, so a
// window focus reloads both and a pin made on another device shows up.
export function usePinnedTaskRecords() {
  return useAuthenticatedQuery(
    taskKeys.list({ pinned: true }),
    async (client) =>
      (
        await client.getTasksWithStatus(
          { pinned: true, basic: true },
          { fetchAll: true },
        )
      ).tasks as unknown as Task[],
    {
      staleTime: 30_000,
      refetchInterval: (query) =>
        pinnedRecordsPollInterval(query.state.data?.length),
    },
  );
}

export function useTaskSummaries(
  ids: string[],
  options?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<TaskSummaryDTO[]>(
    taskKeys.summaries(ids),
    (client) => client.getTaskSummaries(ids),
    {
      enabled: (options?.enabled ?? true) && ids.length > 0,
      refetchInterval: TASK_SUMMARY_POLL_INTERVAL_MS,
      placeholderData: keepPreviousData,
    },
  );
}

// The /tasks/summaries/ endpoint doesn't include origin_product, so fetch the
// slack-origin subset separately and intersect by id in the sidebar. The
// `internal` filter mirrors the sidebar's task-visibility scope so staff
// toggling the internal view still see slack icons on internal tasks.
export function useSlackTasks(options?: {
  enabled?: boolean;
  showInternal?: boolean;
}) {
  const internal = options?.showInternal ? true : undefined;
  return useAuthenticatedQuery<Task[]>(
    taskKeys.list({ originProduct: "slack", internal }),
    (client) =>
      client.getTasks({
        originProduct: "slack",
        internal,
        // Only slack origin/thread fields are read off these rows; ask for the basic payload.
        basic: true,
      }) as unknown as Promise<Task[]>,
    {
      enabled: options?.enabled ?? true,
      refetchInterval: SLACK_TASK_POLL_INTERVAL_MS,
    },
  );
}
