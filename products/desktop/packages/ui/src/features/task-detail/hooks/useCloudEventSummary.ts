import {
  type CloudEventSummary,
  createCloudEventSummaryTracker,
} from "@posthog/core/task-detail/cloudToolChanges";
import { useMemo, useState } from "react";
import { useSessionSelector } from "../../sessions/useSession";

const EMPTY_SUMMARY: CloudEventSummary = {
  toolCalls: new Map(),
  changedFiles: [],
  revision: 0,
  changedFilesRevision: 0,
};

export function useCloudEventSummary(
  taskId: string,
  enabled = true,
): CloudEventSummary {
  const events = useSessionSelector(
    enabled ? taskId : undefined,
    (session) => session?.events,
  );
  const [tracker] = useState(createCloudEventSummaryTracker);
  return useMemo(
    () => (events ? tracker.update(events) : EMPTY_SUMMARY),
    [events, tracker],
  );
}
