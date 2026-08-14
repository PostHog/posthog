import { Cloud as CloudIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { useEffect } from "react";
import { usePanelLayoutStore } from "../../panels/panelLayoutStore";
import { useSessionSelector } from "../../sessions/sessionStore";
import { ShellTerminal } from "../../terminal/ShellTerminal";
import { useTerminalStore } from "../../terminal/terminalStore";
import { useShellProcessPoller } from "../../terminal/useShellProcessPoller";
import { useIsCloudTask, useWorkspace } from "../../workspace/useWorkspace";

interface TaskShellPanelProps {
  taskId: string;
  task: Task;
  shellId?: string;
}

export function TaskShellPanel({ taskId, task, shellId }: TaskShellPanelProps) {
  const stateKey = shellId ? `${taskId}-${shellId}` : taskId;
  const tabId = shellId || "shell";

  // Only the connection status gates rendering here; reading it narrowly keeps
  // the terminal panel from re-rendering on every streamed token.
  const sessionStatus = useSessionSelector(taskId, (s) => s?.status);
  const isCloud = useIsCloudTask(task);
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

  if (isCloud) {
    return (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <CloudIcon size={24} className="text-gray-10" />
          </EmptyMedia>
          <EmptyTitle>Terminal isn't available</EmptyTitle>
          <EmptyDescription>
            This session runs in the cloud, not on this machine.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (!workspacePath || !sessionStatus || sessionStatus === "connecting") {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5 text-(--gray-9)" />
      </div>
    );
  }

  return (
    <div className="h-full">
      <ShellTerminal cwd={workspacePath} stateKey={stateKey} taskId={taskId} />
    </div>
  );
}
