import path from "node:path";
import { getCurrentBranch, getDefaultBranch } from "@posthog/git/queries";
import type { WorkspaceMode } from "@posthog/shared";

export interface WorkspaceEnvContext {
  taskId: string;
  folderPath: string;
  worktreePath: string | null;
  worktreeName: string | null;
  mode: WorkspaceMode;
}

const PORT_BASE = 50000;
const PORTS_PER_WORKSPACE = 20;
const MAX_WORKSPACES = 1000;

function hashTaskId(taskId: string): number {
  let hash = 0;
  for (let i = 0; i < taskId.length; i++) {
    const char = taskId.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash = hash & hash;
  }
  return Math.abs(hash);
}

function allocateWorkspacePorts(taskId: string): {
  start: number;
  end: number;
  ports: number[];
} {
  const workspaceIndex = hashTaskId(taskId) % MAX_WORKSPACES;
  const start = PORT_BASE + workspaceIndex * PORTS_PER_WORKSPACE;
  const end = start + PORTS_PER_WORKSPACE - 1;

  const ports: number[] = [];
  for (let port = start; port <= end; port++) {
    ports.push(port);
  }

  return { start, end, ports };
}

export async function buildWorkspaceEnv(
  context: WorkspaceEnvContext,
): Promise<Record<string, string>> {
  if (context.mode === "cloud") {
    return {};
  }

  const workspaceName =
    context.worktreeName ?? path.basename(context.folderPath);
  const workspacePath = context.worktreePath ?? context.folderPath;
  const rootPath = context.folderPath;

  const defaultBranch = await getDefaultBranch(rootPath);

  const workspaceBranch = (await getCurrentBranch(workspacePath)) ?? "";

  const portAllocation = allocateWorkspacePorts(context.taskId);

  return {
    POSTHOG_CODE: "1",
    POSTHOG_CODE_WORKSPACE_NAME: workspaceName,
    POSTHOG_CODE_WORKSPACE_PATH: workspacePath,
    POSTHOG_CODE_ROOT_PATH: rootPath,
    POSTHOG_CODE_DEFAULT_BRANCH: defaultBranch,
    POSTHOG_CODE_WORKSPACE_BRANCH: workspaceBranch,
    POSTHOG_CODE_WORKSPACE_PORTS: portAllocation.ports.join(","),
    POSTHOG_CODE_WORKSPACE_PORTS_RANGE: String(PORTS_PER_WORKSPACE),
    POSTHOG_CODE_WORKSPACE_PORTS_START: String(portAllocation.start),
    POSTHOG_CODE_WORKSPACE_PORTS_END: String(portAllocation.end),
  };
}
