import { useTerminalStore } from "@posthog/ui/features/terminal/terminalStore";
import { secureRandomString } from "@posthog/ui/utils/random";
import { useMemo } from "react";
import { Terminal } from "./Terminal";

interface ShellTerminalProps {
  cwd?: string;
  stateKey?: string;
  taskId?: string;
}

export function ShellTerminal({ cwd, stateKey, taskId }: ShellTerminalProps) {
  const persistenceKey = stateKey || cwd || "default";

  const savedSessionId = useTerminalStore(
    (state) => state.terminalStates[persistenceKey]?.sessionId,
  );

  const sessionId = useMemo(() => {
    if (savedSessionId) {
      return savedSessionId;
    }
    const newId = `shell-${Date.now()}-${secureRandomString(7)}`;
    useTerminalStore.getState().setSessionId(persistenceKey, newId);
    return newId;
  }, [savedSessionId, persistenceKey]);

  return (
    <Terminal
      sessionId={sessionId}
      persistenceKey={persistenceKey}
      cwd={cwd}
      taskId={taskId}
    />
  );
}
