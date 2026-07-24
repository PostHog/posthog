import { eq, isNotNull } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { taskMetadata } from "../schema";
import type { DatabaseService } from "../service";

export type TaskMetadataRow = typeof taskMetadata.$inferSelect;

const now = () => new Date().toISOString();

/** Fields that can be set on a task-metadata upsert. */
export interface TaskMetadataPatch {
  pinnedAt?: string | null;
  lastViewedAt?: string | null;
  lastActivityAt?: string | null;
  archivedAt?: string | null;
  archivedTitle?: string | null;
  archivedTaskCreatedAt?: string | null;
  archivedRepository?: string | null;
  piSessionFile?: string | null;
}

/**
 * Pin / view / activity metadata for tasks that have no `workspaces` row
 * (repo-less channel tasks whose working dir is a scratch dir). Keyed by task
 * id so the per-device viewed/pinned state persists across reload, just like it
 * does for tasks that own a workspace row.
 */
export interface ITaskMetadataRepository {
  findByTaskId(taskId: string): TaskMetadataRow | null;
  findAll(): TaskMetadataRow[];
  findAllPinned(): TaskMetadataRow[];
  findAllArchived(): TaskMetadataRow[];
  upsert(taskId: string, patch: TaskMetadataPatch): void;
  delete(taskId: string): void;
}

@injectable()
export class TaskMetadataRepository implements ITaskMetadataRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  findByTaskId(taskId: string): TaskMetadataRow | null {
    return (
      this.db
        .select()
        .from(taskMetadata)
        .where(eq(taskMetadata.taskId, taskId))
        .get() ?? null
    );
  }

  findAll(): TaskMetadataRow[] {
    return this.db.select().from(taskMetadata).all();
  }

  findAllPinned(): TaskMetadataRow[] {
    return this.db
      .select()
      .from(taskMetadata)
      .where(isNotNull(taskMetadata.pinnedAt))
      .all();
  }

  findAllArchived(): TaskMetadataRow[] {
    return this.db
      .select()
      .from(taskMetadata)
      .where(isNotNull(taskMetadata.archivedAt))
      .all();
  }

  upsert(taskId: string, patch: TaskMetadataPatch): void {
    const timestamp = now();
    this.db
      .insert(taskMetadata)
      .values({ taskId, ...patch, createdAt: timestamp, updatedAt: timestamp })
      .onConflictDoUpdate({
        target: taskMetadata.taskId,
        set: { ...patch, updatedAt: timestamp },
      })
      .run();
  }

  delete(taskId: string): void {
    this.db.delete(taskMetadata).where(eq(taskMetadata.taskId, taskId)).run();
  }
}
