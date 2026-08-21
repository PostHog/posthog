import type { Schemas } from "@posthog/api-client";
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
  },
  options?: { enabled?: boolean },
) {
  const { data: currentUser } = useMeQuery();
  const createdBy = filters?.showAllUsers ? undefined : currentUser?.id;
  const internal = filters?.showInternal ? true : undefined;

  return useAuthenticatedQuery(
    taskKeys.list({ repository: filters?.repository, createdBy, internal }),
    (client) =>
      client.getTasks({
        repository: filters?.repository,
        createdBy,
        internal,
      }) as unknown as Promise<Task[]>,
    {
      enabled: (options?.enabled ?? true) && !!currentUser?.id,
      refetchInterval: TASK_LIST_POLL_INTERVAL_MS,
    },
  );
}

export function useTaskSummaries(
  ids: string[],
  options?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<Schemas.TaskSummary[]>(
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
      }) as unknown as Promise<Task[]>,
    {
      enabled: options?.enabled ?? true,
      refetchInterval: SLACK_TASK_POLL_INTERVAL_MS,
    },
  );
}
