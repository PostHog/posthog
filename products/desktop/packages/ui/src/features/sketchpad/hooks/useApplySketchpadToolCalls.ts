import type { SketchpadSyncClient } from "@posthog/core/sketchpad/sketchpadSync";
import { applySketchpadToolCalls } from "@posthog/core/sketchpad/toolCallEvents";
import { useSessionSelector } from "@posthog/ui/features/sessions/useSession";
import { useEffect } from "react";

export function useApplySketchpadToolCalls(
  client: SketchpadSyncClient | null,
  taskId: string | undefined,
  onFragmentAdded?: (id: string) => void,
): void {
  const events = useSessionSelector(taskId, (session) => session?.events);

  useEffect(() => {
    if (!client || !taskId || !events) return;
    applySketchpadToolCalls(events, client, taskId, onFragmentAdded);
  }, [client, taskId, events, onFragmentAdded]);
}
