import { useHostTRPCClient } from "@posthog/host-router/react";
import { useEffect } from "react";
import { toast } from "../../primitives/toast";

export function useWorkspaceEvents(taskId: string) {
  const client = useHostTRPCClient();
  useEffect(() => {
    const warningSubscription = client.workspace.onWarning.subscribe(
      undefined,
      {
        onData: (data) => {
          if (data.taskId !== taskId) return;
          toast.warning(data.title, {
            description: data.message,
            duration: 10000,
          });
        },
      },
    );

    return () => {
      warningSubscription.unsubscribe();
    };
  }, [taskId, client]);
}
