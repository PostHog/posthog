import { eq } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { archives } from "../schema";
import type { DatabaseService } from "../service";

export type Archive = typeof archives.$inferSelect;
export type NewArchive = typeof archives.$inferInsert;

export interface CreateArchiveData {
  workspaceId: string;
  branchName: string | null;
  checkpointId: string | null;
  title?: string | null;
  taskCreatedAt?: string | null;
  repository?: string | null;
}

export interface IArchiveRepository {
  findById(id: string): Archive | null;
  findByWorkspaceId(workspaceId: string): Archive | null;
  findAll(): Archive[];
  create(data: CreateArchiveData): Archive;
  updateDetailsByWorkspaceId(
    workspaceId: string,
    details: Pick<CreateArchiveData, "title" | "taskCreatedAt" | "repository">,
  ): void;
  deleteByWorkspaceId(workspaceId: string): void;
  deleteAll(): void;
}

const byId = (id: string) => eq(archives.id, id);
const byWorkspaceId = (wsId: string) => eq(archives.workspaceId, wsId);
const now = () => new Date().toISOString();

@injectable()
export class ArchiveRepository implements IArchiveRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  findById(id: string): Archive | null {
    return this.db.select().from(archives).where(byId(id)).get() ?? null;
  }

  findByWorkspaceId(workspaceId: string): Archive | null {
    return (
      this.db.select().from(archives).where(byWorkspaceId(workspaceId)).get() ??
      null
    );
  }

  findAll(): Archive[] {
    return this.db.select().from(archives).all();
  }

  create(data: CreateArchiveData): Archive {
    const timestamp = now();
    const id = crypto.randomUUID();
    const row: NewArchive = {
      id,
      workspaceId: data.workspaceId,
      branchName: data.branchName,
      checkpointId: data.checkpointId,
      title: data.title ?? null,
      taskCreatedAt: data.taskCreatedAt ?? null,
      repository: data.repository ?? null,
      archivedAt: timestamp,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    this.db.insert(archives).values(row).run();
    const created = this.findById(id);
    if (!created) {
      throw new Error(`Failed to create archive with id ${id}`);
    }
    return created;
  }

  updateDetailsByWorkspaceId(
    workspaceId: string,
    details: Pick<CreateArchiveData, "title" | "taskCreatedAt" | "repository">,
  ): void {
    this.db
      .update(archives)
      .set({ ...details, updatedAt: now() })
      .where(byWorkspaceId(workspaceId))
      .run();
  }

  deleteByWorkspaceId(workspaceId: string): void {
    this.db.delete(archives).where(byWorkspaceId(workspaceId)).run();
  }

  deleteAll(): void {
    this.db.delete(archives).run();
  }
}
