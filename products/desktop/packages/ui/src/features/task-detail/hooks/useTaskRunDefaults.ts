import {
  NO_TASK_RUN_DEFAULTS,
  type TaskRunDefaults,
} from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useRef } from "react";
import { useAuthStateFetched, useAuthStateValue } from "../../auth/store";

export interface TaskRunDefaultsResult {
  defaults: TaskRunDefaults;
  /** Whether the answer is final — the fetch finished, failed, or was never applicable. */
  isSettled: boolean;
}

/**
 * Shared so the settings page can drop this cache when it changes the preference behind
 * it. The composer holds the answer for `staleTime`, which is right for a value that
 * rarely moves and wrong for the moment someone just moved it.
 */
export function taskRunDefaultsQueryKey(
  projectId: number | string | null,
): [string, number | string | null] {
  return ["task-run-defaults", projectId];
}

/**
 * The project/user default AI run configuration for the signed-in user, which
 * the composer opens on when nothing has been picked locally.
 *
 * Defaults are a nicety: an unauthenticated or failed fetch resolves to "no
 * default" so the composer falls back to its built-in selection rather than
 * stalling.
 */
export function useTaskRunDefaults(): TaskRunDefaultsResult {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const authFetched = useAuthStateFetched();
  const query = useAuthenticatedQuery(
    taskRunDefaultsQueryKey(projectId),
    async (client) => await client.getTaskRunDefaults(Number(projectId)),
    {
      enabled: projectId != null,
      // The preference is shared, so it also moves in the web app, in Slack, or via a
      // teammate changing the project default — none of which this app hears about. A
      // short window plus a refetch when the app is focused again keeps it close to the
      // truth without polling; a change made *here* doesn't wait for it, since the write
      // invalidates this key directly.
      staleTime: 30 * 1000,
      refetchOnWindowFocus: true,
      retry: false,
    },
  );

  // Monotonic: `projectId` only arrives once auth bootstraps, so a plain `projectId == null`
  // arm would read settled, then unsettled, then settled — restarting whatever waits on it.
  // Once true it stays true for the life of the hook.
  const settledRef = useRef(false);
  settledRef.current =
    settledRef.current || query.isFetched || (authFetched && projectId == null);

  return {
    defaults: query.data ?? NO_TASK_RUN_DEFAULTS,
    isSettled: settledRef.current,
  };
}
