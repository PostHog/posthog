import {
  type CloudEventSummary,
  createCloudEventSummaryTracker,
} from "@posthog/core/task-detail/cloudToolChanges";
import { useMemo, useRef } from "react";
import { useSessionSelector } from "../../sessions/useSession";

const EMPTY_SUMMARY: CloudEventSummary = {
  toolCalls: new Map(),
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
  const trackerRef = useRef<ReturnType<
    typeof createCloudEventSummaryTracker
  > | null>(null);
  trackerRef.current ??= createCloudEventSummaryTracker();
  const tracker = trackerRef.current;
  return useMemo(
    () => (events ? tracker.update(events) : EMPTY_SUMMARY),
    [events, tracker],
  );
}
