import {
  isTerminalStatus,
  type TaskRun,
  type TaskRunExposedPort,
} from "@posthog/shared/domain-types";
import { useCompletedToolCalls } from "@posthog/ui/features/sessions/components/completedToolCalls";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

const EXPOSE_PORT_TOOL = "expose_port";
const EXPOSED_PORTS_POLL_INTERVAL_MS = 30_000;
const NO_PORTS: TaskRunExposedPort[] = [];

export function useTaskRunExposedPorts(
  taskId: string,
  runId: string | undefined,
  enabled: boolean,
): TaskRunExposedPort[] {
  const events = useSessionSelector(taskId, (session) => session?.events);
  const exposeCalls = useCompletedToolCalls(events ?? [], EXPOSE_PORT_TOOL);
  const query = useAuthenticatedQuery<TaskRun>(
    ["task-run-exposed-ports", taskId, runId ?? "none", exposeCalls],
    (client) => client.getTaskRun(taskId, runId as string),
    {
      enabled: enabled && !!runId,
      refetchInterval: (current) =>
        isTerminalStatus(current.state.data?.status)
          ? false
          : EXPOSED_PORTS_POLL_INTERVAL_MS,
      placeholderData: (previous) => previous,
    },
  );
  return query.data?.exposed_ports ?? NO_PORTS;
}
