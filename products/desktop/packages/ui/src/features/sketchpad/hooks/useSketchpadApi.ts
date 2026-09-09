import type { ISketchpadService } from "@posthog/core/sketchpad/identifiers";
import type { SketchpadApi } from "@posthog/core/sketchpad/sketchpadSync";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useMemo } from "react";

export function useSketchpadApi(): SketchpadApi &
  Pick<ISketchpadService, "compiled"> {
  const trpc = useHostTRPCClient();
  return useMemo<SketchpadApi & Pick<ISketchpadService, "compiled">>(() => {
    return {
      compiled: (id, refs, signal) =>
        trpc.sketchpad.compiled.query({ id, refs }, { signal }),
      get: (id) => trpc.sketchpad.get.query({ id }),
      opsSince: (id, since, limit) =>
        trpc.sketchpad.opsSince.query({ id, since, limit }),
      appendOps: (id, input) =>
        trpc.sketchpad.appendOps.mutate({ id, ...input }),
    };
  }, [trpc]);
}
