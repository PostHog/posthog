export interface SessionCanceller {
  cancelSessionsByTaskId(taskId: string): Promise<void>;
}

export interface ArchiveFileWatcher {
  stopWatching(worktreePath: string): Promise<void>;
}
