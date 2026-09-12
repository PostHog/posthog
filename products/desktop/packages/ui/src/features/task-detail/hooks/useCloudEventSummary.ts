import {
  type CloudEventSummary,
  getCloudEventSummary,
} from "@posthog/core/task-detail/cloudToolChanges";
import { useSessionSelector } from "../../sessions/useSession";

export function useCloudEventSummary(
  taskId: string,
  enabled = true,
): CloudEventSummary {
  return useSessionSelector(enabled ? taskId : undefined, (session) =>
    getCloudEventSummary(session?.events),
  );
}
