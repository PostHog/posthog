import { eq } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { worktrees } from "../schema";
import type { DatabaseService } from "../service";

export type Worktree = typeof worktrees.$inferSelect;
export type NewWorktree = typeof worktrees.$inferInsert;

export interface CreateWorktreeData {
  workspaceId: string;
  name: string;
  path: string;
}

export interface IWorktreeRepository {
  findById(id: string): Worktree | null;
  findByWorkspaceId(workspaceId: string): Worktree | null;
  findByPath(path: string): Worktree | null;
  findAll(): Worktree[];
  create(data: CreateWorktreeData): Worktree;
  updatePath(workspaceId: string, path: string): void;
  deleteByWorkspaceId(workspaceId: string): void;
  deleteAll(): void;
}

const byId = (id: string) => eq(worktrees.id, id);
const byWorkspaceId = (wsId: string) => eq(worktrees.workspaceId, wsId);
const byPath = (path: string) => eq(worktrees.path, path);
const now = () => new Date().toISOString();

@injectable()
export class WorktreeRepository implements IWorktreeRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  findById(id: string): Worktree | null {
    return this.db.select().from(worktrees).where(byId(id)).get() ?? null;
  }

  findByWorkspaceId(workspaceId: string): Worktree | null {
    return (
      this.db
        .select()
        .from(worktrees)
        .where(byWorkspaceId(workspaceId))
        .get() ?? null
    );
  }

  findByPath(path: string): Worktree | null {
    return this.db.select().from(worktrees).where(byPath(path)).get() ?? null;
  }

  findAll(): Worktree[] {
    return this.db.select().from(worktrees).all();
  }

  create(data: CreateWorktreeData): Worktree {
    const timestamp = now();
    const id = crypto.randomUUID();
    const row: NewWorktree = {
      id,
      workspaceId: data.workspaceId,
      name: data.name,
      path: data.path,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    this.db.insert(worktrees).values(row).run();
    const created = this.findById(id);
    if (!created) {
      throw new Error(`Failed to create worktree with id ${id}`);
    }
    return created;
  }

  updatePath(workspaceId: string, path: string): void {
    this.db
      .update(worktrees)
      .set({ path, updatedAt: now() })
      .where(byWorkspaceId(workspaceId))
      .run();
  }

  deleteByWorkspaceId(workspaceId: string): void {
    this.db.delete(worktrees).where(byWorkspaceId(workspaceId)).run();
  }

  deleteAll(): void {
    this.db.delete(worktrees).run();
  }
}
