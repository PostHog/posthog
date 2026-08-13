import { eq } from "drizzle-orm";
import { inject, injectable } from "inversify";
import { DATABASE_SERVICE } from "../identifiers";
import { normalizeDirectoryPath } from "../normalize-path";
import { defaultAdditionalDirectories } from "../schema";
import type { DatabaseService } from "../service";

export type DefaultAdditionalDirectory =
  typeof defaultAdditionalDirectories.$inferSelect;

export interface IDefaultAdditionalDirectoryRepository {
  list(): string[];
  add(path: string): void;
  remove(path: string): void;
}

@injectable()
export class DefaultAdditionalDirectoryRepository
  implements IDefaultAdditionalDirectoryRepository
{
  constructor(
    @inject(DATABASE_SERVICE)
    private readonly databaseService: DatabaseService,
  ) {}

  private get db() {
    return this.databaseService.db;
  }

  list(): string[] {
    return this.db
      .select()
      .from(defaultAdditionalDirectories)
      .all()
      .map((row) => row.path);
  }

  add(path: string): void {
    this.db
      .insert(defaultAdditionalDirectories)
      .values({ path: normalizeDirectoryPath(path) })
      .onConflictDoNothing()
      .run();
  }

  remove(path: string): void {
    this.db
      .delete(defaultAdditionalDirectories)
      .where(
        eq(defaultAdditionalDirectories.path, normalizeDirectoryPath(path)),
      )
      .run();
  }
}
