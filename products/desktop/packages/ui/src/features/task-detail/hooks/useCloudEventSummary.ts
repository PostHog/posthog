import {
  buildCloudEventSummary,
  type CloudEventSummary,
} from "@posthog/core/task-detail/cloudToolChanges";
import { useMemo } from "react";
import { useSessionForTask } from "../../sessions/useSession";

const EMPTY_SUMMARY: CloudEventSummary = {
  toolCalls: new Map(),
};

export function useCloudEventSummary(
  taskId: string,
  enabled = true,
): CloudEventSummary {
  const session = useSessionForTask(enabled ? taskId : undefined);
  const events = session?.events;
  return useMemo(
    () => (events ? buildCloudEventSummary(events) : EMPTY_SUMMARY),
    [events],
  );
}
