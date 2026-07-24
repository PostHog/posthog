import { mergePrUrls, promotePrUrl, type WorkspaceMode } from "@posthog/shared";
import { eq, isNotNull } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { normalizeDirectoryPath } from "../normalize-path";
import { workspaces } from "../schema";
import type { DatabaseService } from "../service";

export type Workspace = typeof workspaces.$inferSelect;
export type NewWorkspace = typeof workspaces.$inferInsert;
export type { WorkspaceMode } from "@posthog/shared";
export type CachedPrState = "open" | "merged" | "closed" | "draft";

export interface CreateWorkspaceData {
  taskId: string;
  repositoryId: string | null;
  mode: WorkspaceMode;
}

export interface PrCacheUpdate {
  prUrl: string | null;
  prState: CachedPrState | null;
  accumulate: boolean;
}

export interface IWorkspaceRepository {
  findById(id: string): Workspace | null;
  findByTaskId(taskId: string): Workspace | null;
  findAllByRepositoryId(repositoryId: string): Workspace[];
  findAllPinned(): Workspace[];
  findAll(): Workspace[];
  create(data: CreateWorkspaceData): Workspace;
  createCloudMany(taskIds: string[]): void;
  deleteByTaskId(taskId: string): void;
  deleteById(id: string): void;
  updatePinnedAt(taskId: string, pinnedAt: string | null): void;
  updateLastViewedAt(taskId: string, lastViewedAt: string): void;
  updateLastActivityAt(taskId: string, lastActivityAt: string): void;
  updateLinkedBranch(taskId: string, linkedBranch: string | null): void;
  updateMode(taskId: string, mode: WorkspaceMode): void;
  setModeAndRepository(
    taskId: string,
    mode: WorkspaceMode,
    repositoryId: string | null,
  ): void;
  getAdditionalDirectories(taskId: string): string[];
  addAdditionalDirectory(taskId: string, path: string): void;
  removeAdditionalDirectory(taskId: string, path: string): void;
  updatePrCache(taskId: string, update: PrCacheUpdate): void;
  getPrUrls(taskId: string): string[];
  promotePrUrl(taskId: string, prUrl: string): void;
  deleteAll(): void;
}

export function parseStringArray(value: string | null | undefined): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed)
      ? parsed.filter((v): v is string => typeof v === "string")
      : [];
  } catch {
    return [];
  }
}

const byId = (id: string) => eq(workspaces.id, id);
const byTaskId = (taskId: string) => eq(workspaces.taskId, taskId);
const byRepositoryId = (repoId: string) => eq(workspaces.repositoryId, repoId);
const isPinned = isNotNull(workspaces.pinnedAt);
const now = () => new Date().toISOString();

@injectable()
export class WorkspaceRepository implements IWorkspaceRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  findById(id: string): Workspace | null {
    return this.db.select().from(workspaces).where(byId(id)).get() ?? null;
  }

  findByTaskId(taskId: string): Workspace | null {
    return (
      this.db.select().from(workspaces).where(byTaskId(taskId)).get() ?? null
    );
  }

  findAllByRepositoryId(repositoryId: string): Workspace[] {
    return this.db
      .select()
      .from(workspaces)
      .where(byRepositoryId(repositoryId))
      .all();
  }

  findAllPinned(): Workspace[] {
    return this.db.select().from(workspaces).where(isPinned).all();
  }

  findAll(): Workspace[] {
    return this.db.select().from(workspaces).all();
  }

  create(data: CreateWorkspaceData): Workspace {
    const timestamp = now();
    const id = crypto.randomUUID();
    const row: NewWorkspace = {
      id,
      taskId: data.taskId,
      repositoryId: data.repositoryId,
      mode: data.mode,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    this.db.insert(workspaces).values(row).run();
    const created = this.findById(id);
    if (!created) {
      throw new Error(`Failed to create workspace with id ${id}`);
    }
    return created;
  }

  createCloudMany(taskIds: string[]): void {
    if (taskIds.length === 0) return;
    const timestamp = now();
    const rows: NewWorkspace[] = taskIds.map((taskId) => ({
      id: crypto.randomUUID(),
      taskId,
      repositoryId: null,
      mode: "cloud",
      createdAt: timestamp,
      updatedAt: timestamp,
    }));
    this.db.insert(workspaces).values(rows).run();
  }

  deleteByTaskId(taskId: string): void {
    this.db.delete(workspaces).where(byTaskId(taskId)).run();
  }

  deleteById(id: string): void {
    this.db.delete(workspaces).where(byId(id)).run();
  }

  updatePinnedAt(taskId: string, pinnedAt: string | null): void {
    this.db
      .update(workspaces)
      .set({ pinnedAt, updatedAt: now() })
      .where(byTaskId(taskId))
      .run();
  }

  updateLastViewedAt(taskId: string, lastViewedAt: string): void {
    this.db
      .update(workspaces)
      .set({ lastViewedAt, updatedAt: now() })
      .where(byTaskId(taskId))
      .run();
  }

  updateLastActivityAt(taskId: string, lastActivityAt: string): void {
    this.db
      .update(workspaces)
      .set({ lastActivityAt, updatedAt: now() })
      .where(byTaskId(taskId))
      .run();
  }

  updateLinkedBranch(taskId: string, linkedBranch: string | null): void {
    this.db
      .update(workspaces)
      .set({ linkedBranch, updatedAt: now() })
      .where(byTaskId(taskId))
      .run();
  }

  updateMode(taskId: string, mode: WorkspaceMode): void {
    this.db
      .update(workspaces)
      .set({ mode, updatedAt: now() })
      .where(byTaskId(taskId))
      .run();
  }

  setModeAndRepository(
    taskId: string,
    mode: WorkspaceMode,
    repositoryId: string | null,
  ): void {
    this.db
      .update(workspaces)
      .set({ mode, repositoryId, updatedAt: now() })
      .where(byTaskId(taskId))
      .run();
  }

  getAdditionalDirectories(taskId: string): string[] {
    const workspace = this.findByTaskId(taskId);
    return parseStringArray(workspace?.additionalDirectories);
  }

  private updateDirectories(
    taskId: string,
    update: (current: string[]) => string[] | null,
  ): void {
    const next = update(this.getAdditionalDirectories(taskId));
    if (next === null) return;
    this.db
      .update(workspaces)
      .set({ additionalDirectories: JSON.stringify(next), updatedAt: now() })
      .where(byTaskId(taskId))
      .run();
  }

  addAdditionalDirectory(taskId: string, path: string): void {
    const normalized = normalizeDirectoryPath(path);
    this.updateDirectories(taskId, (current) =>
      current.includes(normalized) ? null : [...current, normalized],
    );
  }

  removeAdditionalDirectory(taskId: string, path: string): void {
    const normalized = normalizeDirectoryPath(path);
    this.updateDirectories(taskId, (current) =>
      current.includes(normalized)
        ? current.filter((p) => p !== normalized)
        : null,
    );
  }

  updatePrCache(taskId: string, update: PrCacheUpdate): void {
    const existing = parseStringArray(this.findByTaskId(taskId)?.prUrls);
    const prUrls =
      update.prUrl && update.accumulate
        ? mergePrUrls(existing, [update.prUrl])
        : existing;
    this.db
      .update(workspaces)
      .set({
        prUrl: update.prUrl,
        prState: update.prState,
        prUrls: JSON.stringify(prUrls),
        updatedAt: now(),
      })
      .where(byTaskId(taskId))
      .run();
  }

  getPrUrls(taskId: string): string[] {
    return parseStringArray(this.findByTaskId(taskId)?.prUrls);
  }

  promotePrUrl(taskId: string, prUrl: string): void {
    const prUrls = promotePrUrl(this.getPrUrls(taskId), prUrl);
    this.db
      .update(workspaces)
      .set({ prUrls: JSON.stringify(prUrls), updatedAt: now() })
      .where(byTaskId(taskId))
      .run();
  }

  deleteAll(): void {
    this.db.delete(workspaces).run();
  }
}
