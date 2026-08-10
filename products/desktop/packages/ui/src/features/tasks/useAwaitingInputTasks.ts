import type { Task } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";
import { taskKeys } from "./taskKeys";

// The server is the only thing that knows a run is waiting while nothing is attached to it, and
// a request that arrives while the app is closed has no other way in. Polled rather than
// streamed because it is the fallback: a session that is attached reports its own prompts.
const AWAITING_INPUT_POLL_INTERVAL_MS = 60_000;

const NO_TASKS: Task[] = [];

/**
 * Tasks with a live run blocked on someone answering a permission request, whoever raised it.
 *
 * Its job is the first seconds after launch, before any session is attached: the app has to be
 * able to say which sessions want you without having replayed their event logs. A session that
 * is attached overrides this for its own task, because it sees the prompt and the answer as they
 * happen. Deliberately not scoped to the loaded task list, which is one page of the newest tasks
 * and can leave out the very run that is waiting.
 */
export function useAwaitingInputTasks(): Task[] {
  const { data } = useAuthenticatedQuery(
    taskKeys.list({ awaitingInput: true }),
    (client) => client.getTasks({ awaitingInput: true }),
    { refetchInterval: AWAITING_INPUT_POLL_INTERVAL_MS },
  );
  return useMemo(
    // The filter is read off the rows rather than trusted from the request: a server that does
    // not know the query parameter yet ignores it and answers with every task, and a client that
    // took that at its word would mark the whole list as waiting on you.
    () => data?.filter((task) => task.latest_run?.awaiting_input) ?? NO_TASKS,
    [data],
  );
}
