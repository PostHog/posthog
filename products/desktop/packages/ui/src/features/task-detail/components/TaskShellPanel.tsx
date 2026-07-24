import type { Task } from "@posthog/shared/domain-types";
import { Box } from "@radix-ui/themes";
import { useEffect } from "react";
import { usePanelLayoutStore } from "../../panels/panelLayoutStore";
import { useSessionSelector } from "../../sessions/sessionStore";
import { ShellTerminal } from "../../terminal/ShellTerminal";
import { useTerminalStore } from "../../terminal/terminalStore";
import { useShellProcessPoller } from "../../terminal/useShellProcessPoller";
import { useWorkspace } from "../../workspace/useWorkspace";

interface TaskShellPanelProps {
  taskId: string;
  task: Task;
  shellId?: string;
}

export function TaskShellPanel({
  taskId,
  task: _task,
  shellId,
}: TaskShellPanelProps) {
  const stateKey = shellId ? `${taskId}-${shellId}` : taskId;
  const tabId = shellId || "shell";

  // Only the connection status gates rendering here; reading it narrowly keeps
  // the terminal panel from re-rendering on every streamed token.
  const sessionStatus = useSessionSelector(taskId, (s) => s?.status);
  const workspace = useWorkspace(taskId);
  const workspacePath = workspace?.worktreePath ?? workspace?.folderPath;

  const processName = useTerminalStore(
    (state) => state.terminalStates[stateKey]?.processName,
  );
  const updateTabLabel = usePanelLayoutStore((state) => state.updateTabLabel);

  useShellProcessPoller(stateKey);

  useEffect(() => {
    if (processName) {
      updateTabLabel(taskId, tabId, processName);
    }
  }, [processName, taskId, tabId, updateTabLabel]);

  if (!workspacePath || !sessionStatus || sessionStatus === "connecting") {
    return null;
  }

  return (
    <Box height="100%">
      <ShellTerminal cwd={workspacePath} stateKey={stateKey} taskId={taskId} />
    </Box>
  );
}
