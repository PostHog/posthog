export interface GitStateChangedEvent {
  repoPath: string;
}

export interface BranchRenamedEvent {
  mainRepoPath: string;
  worktreePath: string;
  oldBranch: string;
  newBranch: string;
}

export interface AgentFileActivityEvent {
  taskId: string;
  branchName: string | null;
}

export interface WorkspaceFileWatcher {
  stopWatching(worktreePath: string): Promise<void>;
  onGitStateChanged(handler: (event: GitStateChangedEvent) => void): void;
}

export interface WorkspaceFocus {
  onBranchRenamed(handler: (event: BranchRenamedEvent) => void): void;
}

export interface WorkspaceAgent {
  cancelSessionsByTaskId(taskId: string): Promise<void>;
  onAgentFileActivity(handler: (event: AgentFileActivityEvent) => void): void;
}

export interface WorkspaceProvisioning {
  emitOutput(taskId: string, data: string): void;
}
