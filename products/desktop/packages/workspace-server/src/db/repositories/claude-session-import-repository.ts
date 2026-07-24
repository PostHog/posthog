import { desc, eq, inArray, sql } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { claudeSessionImports } from "../schema";
import type { DatabaseService } from "../service";

export type ClaudeSessionImport = typeof claudeSessionImports.$inferSelect;
export type NewClaudeSessionImport = typeof claudeSessionImports.$inferInsert;

export interface RecordClaudeSessionImportData {
  sourceSessionId: string;
  importedSessionId: string;
  taskId: string;
  repoPath: string;
  sourceMtimeMs: number;
  sourceSizeBytes: number;
  sourceLastEntryUuid: string | null;
}

export interface IClaudeSessionImportRepository {
  recordImport(data: RecordClaudeSessionImportData): ClaudeSessionImport;
  /** Latest import per source session id, newest first within each source. */
  listBySourceSessionIds(sourceSessionIds: string[]): ClaudeSessionImport[];
  findByTaskId(taskId: string): ClaudeSessionImport | null;
  deleteByTaskId(taskId: string): void;
  deleteByImportedSessionId(importedSessionId: string): void;
  deleteAll(): void;
}

@injectable()
export class ClaudeSessionImportRepository
  implements IClaudeSessionImportRepository
{
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  recordImport(data: RecordClaudeSessionImportData): ClaudeSessionImport {
    const id = crypto.randomUUID();
    this.db
      .insert(claudeSessionImports)
      .values({ id, ...data })
      .run();
    const created = this.db
      .select()
      .from(claudeSessionImports)
      .where(eq(claudeSessionImports.id, id))
      .get();
    if (!created) {
      throw new Error(`Failed to record claude session import ${id}`);
    }
    return created;
  }

  listBySourceSessionIds(sourceSessionIds: string[]): ClaudeSessionImport[] {
    if (sourceSessionIds.length === 0) return [];
    return (
      this.db
        .select()
        .from(claudeSessionImports)
        .where(inArray(claudeSessionImports.sourceSessionId, sourceSessionIds))
        // rowid tiebreaks same-second createdAt, so "newest first" is stable.
        .orderBy(desc(claudeSessionImports.createdAt), desc(sql`rowid`))
        .all()
    );
  }

  findByTaskId(taskId: string): ClaudeSessionImport | null {
    return (
      this.db
        .select()
        .from(claudeSessionImports)
        .where(eq(claudeSessionImports.taskId, taskId))
        .get() ?? null
    );
  }

  deleteByTaskId(taskId: string): void {
    this.db
      .delete(claudeSessionImports)
      .where(eq(claudeSessionImports.taskId, taskId))
      .run();
  }

  deleteByImportedSessionId(importedSessionId: string): void {
    this.db
      .delete(claudeSessionImports)
      .where(eq(claudeSessionImports.importedSessionId, importedSessionId))
      .run();
  }

  deleteAll(): void {
    this.db.delete(claudeSessionImports).run();
  }
}
