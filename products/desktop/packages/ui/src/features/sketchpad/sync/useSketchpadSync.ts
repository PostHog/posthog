import {
  type SketchpadApi,
  SketchpadSyncClient,
  type SketchpadSyncState,
} from "@posthog/core/sketchpad/sketchpadSync";
import { toast } from "@posthog/ui/primitives/toast";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { useEffect, useMemo } from "react";
import { useStore } from "zustand";

export interface SketchpadSyncActorUser {
  userId?: number;
  userName?: string;
}

export function useSketchpadSync(
  sketchpadId: string,
  api: SketchpadApi,
  actorUser?: SketchpadSyncActorUser,
): { state: SketchpadSyncState; client: SketchpadSyncClient } {
  const client = useMemo(
    () =>
      new SketchpadSyncClient(api, sketchpadId, {
        pendingStorage:
          actorUser?.userId === undefined
            ? undefined
            : {
                storage: stateStorage,
                key: `sketchpad-pending:${actorUser.userId}:${sketchpadId}`,
              },
      }),
    [api, sketchpadId, actorUser?.userId],
  );
  const state = useStore(client.store);

  useEffect(() => client.setActorUser(actorUser), [client, actorUser]);

  useEffect(
    () =>
      client.store.subscribe((next, previous) => {
        if (next.lastError && next.lastError !== previous.lastError) {
          toast.error("Sketchpad sync failed", {
            id: `board-sync-${sketchpadId}`,
            description: next.lastError,
          });
        }
      }),
    [sketchpadId, client],
  );

  useEffect(() => {
    if (actorUser?.userId === undefined) return;
    let live = true;
    void client.load().then(() => {
      if (live) client.start();
    });
    return () => {
      live = false;
      client.stop();
    };
  }, [client, actorUser?.userId]);

  useEffect(() => {
    const onVisibility = (): void => {
      client.setVisible(document.visibilityState === "visible");
    };
    const onFocus = (): void => {
      client.setVisible(true);
      void client.poll();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
    };
  }, [client]);

  return { state, client };
}
