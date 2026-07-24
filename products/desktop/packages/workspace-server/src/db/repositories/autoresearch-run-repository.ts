import { asc, eq, isNull } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { autoresearchRuns } from "../schema";
import type { DatabaseService } from "../service";

export type AutoresearchRunRow = typeof autoresearchRuns.$inferSelect;

const now = () => new Date().toISOString();

export interface AutoresearchRunUpsert {
  id: string;
  taskId: string;
  /** ISO timestamp when the run reached a terminal status; null while open. */
  endedAt: string | null;
  /** JSON-serialized core AutoresearchRun. */
  data: string;
}

/**
 * Persisted autoresearch runs. The run itself is an opaque JSON blob owned
 * by @posthog/core; this repository only stores it and answers the two
 * queries the app needs: a task history and the open runs worth
 * resuming after a restart.
 */
export interface IAutoresearchRunRepository {
  findByTaskId(taskId: string): AutoresearchRunRow[];
  findOpen(): AutoresearchRunRow[];
  upsert(run: AutoresearchRunUpsert): void;
  deleteByTaskId(taskId: string): void;
}

@injectable()
export class AutoresearchRunRepository implements IAutoresearchRunRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  findByTaskId(taskId: string): AutoresearchRunRow[] {
    return this.db
      .select()
      .from(autoresearchRuns)
      .where(eq(autoresearchRuns.taskId, taskId))
      .orderBy(asc(autoresearchRuns.createdAt))
      .all();
  }

  findOpen(): AutoresearchRunRow[] {
    return this.db
      .select()
      .from(autoresearchRuns)
      .where(isNull(autoresearchRuns.endedAt))
      .all();
  }

  upsert(run: AutoresearchRunUpsert): void {
    const timestamp = now();
    this.db
      .insert(autoresearchRuns)
      .values({ ...run, createdAt: timestamp, updatedAt: timestamp })
      .onConflictDoUpdate({
        target: autoresearchRuns.id,
        set: {
          taskId: run.taskId,
          endedAt: run.endedAt,
          data: run.data,
          updatedAt: timestamp,
        },
      })
      .run();
  }

  deleteByTaskId(taskId: string): void {
    this.db
      .delete(autoresearchRuns)
      .where(eq(autoresearchRuns.taskId, taskId))
      .run();
  }
}
