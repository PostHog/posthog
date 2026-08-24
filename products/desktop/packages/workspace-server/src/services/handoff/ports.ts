import type { HandoffChangedFile, HandoffLocalGitState } from "@posthog/shared";

/**
 * Git operations the handoff host needs. The git CLI runs in the
 * workspace-server child process, so the desktop fulfills this with a thin
 * transport adapter over the workspace client.
 */
export interface HandoffGitGateway {
  getChangedFiles(repoPath: string): Promise<readonly HandoffChangedFile[]>;
  getLocalGitState(repoPath: string): Promise<HandoffLocalGitState>;
  cleanupAfterCloudHandoff(
    repoPath: string,
    branchName: string | null,
  ): Promise<{
    stashed: boolean;
    switched: boolean;
    defaultBranch: string | null;
  }>;
}

/**
 * Local NDJSON log-cache operations the handoff host needs, served by the
 * workspace-server local-logs capability.
 */
export interface HandoffLogGateway {
  seedLocalLogs(taskRunId: string, content: string): Promise<void>;
  countLocalLogEntries(taskRunId: string): Promise<number>;
  deleteLocalLogCache(taskRunId: string): Promise<void>;
}
