export const LOGS_SERVICE = Symbol.for("posthog.workspace.logsService");

export interface ILogsService {
  fetchS3Logs(logUrl: string): Promise<string | null>;
  readLocalLogs(taskRunId: string): Promise<string | null>;
  /**
   * Like `readLocalLogs`, but collapses superseded `tool_call_update` snapshots
   * before returning. `totalLineCount` is the original pre-collapse line count.
   */
  readLocalLogsCollapsed(
    taskRunId: string,
  ): Promise<{ content: string; totalLineCount: number } | null>;
  /**
   * Read only the last `maxBytes` of the log for a fast initial paint. Returns
   * `truncated: true` when older history was skipped (the partial first line is
   * dropped). `null` if there's no local log.
   */
  readLocalLogsTail(
    taskRunId: string,
    maxBytes: number,
  ): Promise<{ content: string; truncated: boolean } | null>;
  writeLocalLogs(taskRunId: string, content: string): Promise<void>;
}
