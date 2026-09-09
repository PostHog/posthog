import { SketchpadPresenceSender } from "@posthog/core/sketchpad/sketchpadPresenceSender";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useLayoutEffect, useMemo, useRef } from "react";

export type PresenceSenderHandle = Pick<
  SketchpadPresenceSender,
  "reportCursor" | "reportSelection" | "reportViewport" | "reportCaret"
> & { clientId: string };

export function usePresenceSender(sketchpadId: string): PresenceSenderHandle {
  const client = useHostTRPCClient();
  const clientRef = useRef(client);
  const senderRef = useRef<SketchpadPresenceSender | null>(null);
  const clientId = useMemo(
    () => `${sketchpadId.slice(0, 8)}-${globalThis.crypto.randomUUID()}`,
    [sketchpadId],
  );

  useLayoutEffect(() => {
    clientRef.current = client;
  }, [client]);

  useLayoutEffect(() => {
    const sender = new SketchpadPresenceSender(clientId, (presence) =>
      clientRef.current.sketchpadStream.sendPresence.mutate({
        id: sketchpadId,
        presence,
      }),
    );
    senderRef.current = sender;
    const onBlur = (): void => sender.reportCursor(null);
    window.addEventListener("blur", onBlur);
    return () => {
      senderRef.current = null;
      sender.stop();
      window.removeEventListener("blur", onBlur);
    };
  }, [sketchpadId, clientId]);

  return useMemo(
    () =>
      ({
        clientId,
        reportCursor: (world) => senderRef.current?.reportCursor(world),
        reportSelection: (ids) => senderRef.current?.reportSelection(ids),
        reportViewport: (viewport) =>
          senderRef.current?.reportViewport(viewport),
        reportCaret: (caret) => senderRef.current?.reportCaret(caret),
      }) satisfies PresenceSenderHandle,
    [clientId],
  );
}
