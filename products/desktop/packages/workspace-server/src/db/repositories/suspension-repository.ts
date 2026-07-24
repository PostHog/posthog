import { eq } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { suspensions } from "../schema.js";
import type { DatabaseService } from "../service.js";

export type Suspension = typeof suspensions.$inferSelect;
export type NewSuspension = typeof suspensions.$inferInsert;

type SuspensionReason = "max_worktrees" | "inactivity" | "manual";

export type { SuspensionReason };

export interface CreateSuspensionData {
  workspaceId: string;
  branchName: string | null;
  checkpointId: string | null;
  reason: SuspensionReason;
}

export interface SuspensionRepository {
  findById(id: string): Suspension | null;
  findByWorkspaceId(workspaceId: string): Suspension | null;
  findAll(): Suspension[];
  create(data: CreateSuspensionData): Suspension;
  deleteByWorkspaceId(workspaceId: string): void;
  deleteAll(): void;
}

const byId = (id: string) => eq(suspensions.id, id);
const byWorkspaceId = (wsId: string) => eq(suspensions.workspaceId, wsId);
const now = () => new Date().toISOString();

@injectable()
export class SuspensionRepositoryImpl implements SuspensionRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  findById(id: string): Suspension | null {
    return this.db.select().from(suspensions).where(byId(id)).get() ?? null;
  }

  findByWorkspaceId(workspaceId: string): Suspension | null {
    return (
      this.db
        .select()
        .from(suspensions)
        .where(byWorkspaceId(workspaceId))
        .get() ?? null
    );
  }

  findAll(): Suspension[] {
    return this.db.select().from(suspensions).all();
  }

  create(data: CreateSuspensionData): Suspension {
    const timestamp = now();
    const id = crypto.randomUUID();
    const row: NewSuspension = {
      id,
      workspaceId: data.workspaceId,
      branchName: data.branchName,
      checkpointId: data.checkpointId,
      reason: data.reason,
      suspendedAt: timestamp,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    this.db.insert(suspensions).values(row).run();
    const created = this.findById(id);
    if (!created) {
      throw new Error(`Failed to create suspension with id ${id}`);
    }
    return created;
  }

  deleteByWorkspaceId(workspaceId: string): void {
    this.db.delete(suspensions).where(byWorkspaceId(workspaceId)).run();
  }

  deleteAll(): void {
    this.db.delete(suspensions).run();
  }
}
