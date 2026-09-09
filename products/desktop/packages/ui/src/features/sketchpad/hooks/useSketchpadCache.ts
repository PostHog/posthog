import type { SketchpadSyncState } from "@posthog/core/sketchpad/sketchpadSync";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { createSketchpadCache } from "@posthog/shared";
import { useEffect } from "react";

const WRITE_DELAY_MS = 400;

export function useSketchpadCache(
  sketchpadId: string,
  state: SketchpadSyncState,
): void {
  const client = useHostTRPCClient();
  const { name, headSeq, snapshot, status } = state;

  useEffect(() => {
    if (status !== "synced") return;
    const timer = setTimeout(() => {
      void client.sketchpadCache.write
        .mutate(createSketchpadCache({ sketchpadId, name, headSeq, snapshot }))
        .catch(() => undefined);
    }, WRITE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [sketchpadId, client, name, headSeq, snapshot, status]);
}
