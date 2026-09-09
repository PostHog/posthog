import { useHostTRPCClient } from "@posthog/host-router/react";
import type { SketchpadLogEntry, SketchpadPresence } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { useEffect, useRef } from "react";

const log = logger.scope("sketchpad-stream");

export interface SketchpadStreamHandlers {
  onOp: (entry: SketchpadLogEntry) => void;
  onPresence: (presence: SketchpadPresence) => void;
  onReload: (since: number) => void;
  onLive: (live: boolean) => void;
}

export function useSketchpadStream(
  sketchpadId: string,
  handlers: SketchpadStreamHandlers,
): void {
  const client = useHostTRPCClient();
  const latest = useRef(handlers);
  latest.current = handlers;

  useEffect(() => {
    const subscription = client.sketchpadStream.onSketchpadEvent.subscribe(
      { id: sketchpadId },
      {
        onData: (event) => {
          switch (event.type) {
            case "op":
              latest.current.onOp(event.entry);
              break;
            case "presence":
              latest.current.onPresence(event.presence);
              break;
            case "reload":
              latest.current.onReload(event.since);
              break;
            case "live":
              log.info("board stream live", {
                sketchpadId,
                live: event.live,
              });
              latest.current.onLive(event.live);
              break;
            case "error":
              log.warn("board stream error", { message: event.message });
              break;
          }
        },
        onError: (error) => {
          log.warn("board stream dropped", { message: String(error) });
          latest.current.onLive(false);
        },
      },
    );

    return () => {
      subscription.unsubscribe();
      latest.current.onLive(false);
    };
  }, [sketchpadId, client]);
}
