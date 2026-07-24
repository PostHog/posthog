export interface SessionCanceller {
  cancelSessionsByTaskId(taskId: string): Promise<void>;
}

export interface SuspensionFileWatcher {
  stopWatching(worktreePath: string): Promise<void>;
}
