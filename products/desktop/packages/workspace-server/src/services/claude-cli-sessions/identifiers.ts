import type {
  DeleteImportedCliSessionInput,
  DeleteImportRecordInput,
  ImportCliSessionInput,
  ImportCliSessionOutput,
  ListCliSessionsInput,
  ListCliSessionsOutput,
  RecordCliImportInput,
} from "./schemas";

export const CLAUDE_CLI_SESSIONS_SERVICE = Symbol.for(
  "posthog.workspace.claudeCliSessions",
);

export const IMPORTED_SESSION_CLEANER = Symbol.for(
  "posthog.workspace.importedSessionCleaner",
);

/**
 * Narrow contract for removing a task's imported CLI snapshot + record when the
 * task is deleted. Consumed by the workspace and archive services so neither
 * needs the full sessions service. Implemented by ClaudeCliSessionsService.
 */
export interface ImportedSessionCleaner {
  /** Remove the imported snapshot + record for a task (no-op if not imported). */
  deleteImportForTask(taskId: string): Promise<void>;
}

export interface ClaudeCliSessionsService extends ImportedSessionCleaner {
  listForRepo(input: ListCliSessionsInput): Promise<ListCliSessionsOutput>;
  importSession(input: ImportCliSessionInput): Promise<ImportCliSessionOutput>;
  deleteImportedSession(input: DeleteImportedCliSessionInput): Promise<void>;
  recordImport(input: RecordCliImportInput): Promise<void>;
  deleteImportRecord(input: DeleteImportRecordInput): Promise<void>;
}
