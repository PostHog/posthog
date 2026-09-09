import {
  type PresencePeer,
  SketchpadPresenceTracker,
} from "@posthog/core/sketchpad/sketchpadPresence";
import type { SketchpadPresence } from "@posthog/shared";
import { useCallback, useEffect, useMemo, useState } from "react";

const PRUNE_INTERVAL_MS = 2_000;

export interface SketchpadPeersHandle {
  peers: PresencePeer[];
  ingest: (presence: SketchpadPresence) => void;
}

export function useSketchpadPeers(localClientId: string): SketchpadPeersHandle {
  const [peers, setPeers] = useState<PresencePeer[]>([]);

  const tracker = useMemo(
    () =>
      new SketchpadPresenceTracker({
        localClientId,
        unknownName: "Someone",
        onChange: setPeers,
      }),
    [localClientId],
  );

  useEffect(() => {
    setPeers([]);
    const timer = setInterval(() => tracker.prune(), PRUNE_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      tracker.clear();
    };
  }, [tracker]);

  const ingest = useCallback(
    (presence: SketchpadPresence) => tracker.ingest(presence),
    [tracker],
  );

  return { peers, ingest };
}
