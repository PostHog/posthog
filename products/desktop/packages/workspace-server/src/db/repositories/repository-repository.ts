import { desc, eq } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { repositories } from "../schema";
import type { DatabaseService } from "../service";

export type Repository = typeof repositories.$inferSelect;
export type NewRepository = typeof repositories.$inferInsert;

export interface IRepositoryRepository {
  findAll(): Repository[];
  findById(id: string): Repository | null;
  findByPath(path: string): Repository | null;
  findByRemoteUrl(remoteUrl: string): Repository | null;
  findMostRecentlyAccessed(): Repository | null;
  create(data: { path: string; remoteUrl?: string; id?: string }): Repository;
  upsertByPath(path: string, id?: string): Repository;
  updateLastAccessed(id: string): void;
  updateRemoteUrl(id: string, remoteUrl: string): void;
  delete(id: string): void;
  deleteAll(): void;
}

const byId = (id: string) => eq(repositories.id, id);
const byPath = (path: string) => eq(repositories.path, path);
const byRemoteUrl = (remoteUrl: string) =>
  eq(repositories.remoteUrl, remoteUrl);
const now = () => new Date().toISOString();

@injectable()
export class RepositoryRepository implements IRepositoryRepository {
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  findAll(): Repository[] {
    return this.db.select().from(repositories).all();
  }

  findById(id: string): Repository | null {
    return this.db.select().from(repositories).where(byId(id)).get() ?? null;
  }

  findByPath(path: string): Repository | null {
    return (
      this.db.select().from(repositories).where(byPath(path)).get() ?? null
    );
  }

  findByRemoteUrl(repoKey: string): Repository | null {
    return (
      this.db.select().from(repositories).where(byRemoteUrl(repoKey)).get() ??
      null
    );
  }

  findMostRecentlyAccessed(): Repository | null {
    return (
      this.db
        .select()
        .from(repositories)
        .orderBy(desc(repositories.lastAccessedAt))
        .limit(1)
        .get() ?? null
    );
  }

  create(data: { path: string; remoteUrl?: string; id?: string }): Repository {
    const timestamp = now();
    const id = data.id ?? crypto.randomUUID();
    const row: NewRepository = {
      id,
      path: data.path,
      remoteUrl: data.remoteUrl,
      lastAccessedAt: timestamp,
      createdAt: timestamp,
      updatedAt: timestamp,
    };
    this.db.insert(repositories).values(row).run();
    const created = this.findById(id);
    if (!created) {
      throw new Error(`Failed to create repository with id ${id}`);
    }
    return created;
  }

  upsertByPath(path: string, id?: string): Repository {
    const existing = this.findByPath(path);
    if (existing) {
      this.updateLastAccessed(existing.id);
      const updated = this.findById(existing.id);
      if (!updated) {
        throw new Error(`Repository ${existing.id} not found after update`);
      }
      return updated;
    }
    return this.create({ path, id });
  }

  updateLastAccessed(id: string): void {
    const timestamp = now();
    this.db
      .update(repositories)
      .set({ lastAccessedAt: timestamp, updatedAt: timestamp })
      .where(byId(id))
      .run();
  }

  updateRemoteUrl(id: string, remoteUrl: string): void {
    this.db
      .update(repositories)
      .set({ remoteUrl, updatedAt: now() })
      .where(byId(id))
      .run();
  }

  delete(id: string): void {
    this.db.delete(repositories).where(byId(id)).run();
  }

  deleteAll(): void {
    this.db.delete(repositories).run();
  }
}
