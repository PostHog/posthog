import type {
  ClaudeSessionImport,
  IClaudeSessionImportRepository,
  RecordClaudeSessionImportData,
} from "./claude-session-import-repository";

export interface MockClaudeSessionImportRepository
  extends IClaudeSessionImportRepository {
  _imports: Map<string, ClaudeSessionImport>;
}

export function createMockClaudeSessionImportRepository(): MockClaudeSessionImportRepository {
  const imports = new Map<string, ClaudeSessionImport>();

  return {
    _imports: imports,
    recordImport: (data: RecordClaudeSessionImportData) => {
      const row: ClaudeSessionImport = {
        id: crypto.randomUUID(),
        ...data,
        createdAt: new Date().toISOString(),
      };
      imports.set(row.id, row);
      return { ...row };
    },
    // Map iteration is insertion order; reverse for newest-first, matching the
    // repo's createdAt + rowid ordering.
    listBySourceSessionIds: (sourceSessionIds: string[]) =>
      Array.from(imports.values())
        .filter((row) => sourceSessionIds.includes(row.sourceSessionId))
        .reverse()
        .map((row) => ({ ...row })),
    findByTaskId: (taskId: string) => {
      const row = Array.from(imports.values()).find((r) => r.taskId === taskId);
      return row ? { ...row } : null;
    },
    deleteByTaskId: (taskId: string) => {
      for (const [id, row] of imports) {
        if (row.taskId === taskId) imports.delete(id);
      }
    },
    deleteByImportedSessionId: (importedSessionId: string) => {
      for (const [id, row] of imports) {
        if (row.importedSessionId === importedSessionId) imports.delete(id);
      }
    },
    deleteAll: () => {
      imports.clear();
    },
  };
}
