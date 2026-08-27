import { Cloud as CloudIcon, FolderDashed } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { type ReactNode, useEffect } from "react";
import { usePanelLayoutStore } from "../../panels/panelLayoutStore";
import { useSessionSelector } from "../../sessions/sessionStore";
import { ShellTerminal } from "../../terminal/ShellTerminal";
import { useTerminalStore } from "../../terminal/terminalStore";
import { useShellProcessPoller } from "../../terminal/useShellProcessPoller";
import {
  useIsCloudTask,
  useWorkspace,
  useWorkspaceLoaded,
} from "../../workspace/useWorkspace";

interface TaskShellPanelProps {
  taskId: string;
  task: Task;
  shellId?: string;
}

function TerminalUnavailable({
  icon,
  description,
}: {
  icon: ReactNode;
  description: string;
}) {
  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">{icon}</EmptyMedia>
        <EmptyTitle>Terminal isn't available</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

export function TaskShellPanel({ taskId, task, shellId }: TaskShellPanelProps) {
  const stateKey = shellId ? `${taskId}-${shellId}` : taskId;
  const tabId = shellId || "shell";

  // Only the connection status gates rendering here; reading it narrowly keeps
  // the terminal panel from re-rendering on every streamed token.
  const sessionStatus = useSessionSelector(taskId, (s) => s?.status);
  const isCloud = useIsCloudTask(task);
  const workspace = useWorkspace(taskId);
  const workspaceLoaded = useWorkspaceLoaded();
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
      <TerminalUnavailable
        icon={<CloudIcon size={24} className="text-gray-10" />}
        description="This session runs in the cloud, not on this machine."
      />
    );
  }

  if (workspaceLoaded && !workspacePath) {
    return (
      <TerminalUnavailable
        icon={<FolderDashed size={24} className="text-gray-10" />}
        description="This task doesn't have a local workspace on this machine."
      />
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
