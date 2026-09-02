import {
  getActionSessionId,
  useActionStore,
} from "@posthog/ui/features/actions/actionStore";
import { useCallback, useEffect, useMemo } from "react";
import { Terminal } from "./Terminal";

interface ActionTerminalProps {
  actionId: string;
  command: string;
  cwd: string;
  taskId?: string;
}

export function ActionTerminal({
  actionId,
  command,
  cwd,
  taskId,
}: ActionTerminalProps) {
  const generation = useActionStore(
    (state) => state.generations[actionId] ?? 0,
  );
  const sessionId = useMemo(
    () => getActionSessionId(actionId, generation),
    [actionId, generation],
  );
  const setStatus = useActionStore((state) => state.setStatus);
  const currentStatus = useActionStore((state) => state.statuses[actionId]);

  useEffect(() => {
    if (!currentStatus) {
      setStatus(actionId, "running");
    }
  }, [actionId, currentStatus, setStatus]);

  const handleExit = useCallback(
    (exitCode?: number) => {
      const status = exitCode === 0 ? "success" : "error";
      setStatus(actionId, status);
    },
    [actionId, setStatus],
  );

  return (
    <Terminal
      key={sessionId}
      sessionId={sessionId}
      persistenceKey={sessionId}
      cwd={cwd}
      taskId={taskId}
      command={command}
      onExit={handleExit}
    />
  );
}
