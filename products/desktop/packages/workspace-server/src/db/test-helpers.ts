import path from "node:path";
import Database from "better-sqlite3";
import {
  type BetterSQLite3Database,
  drizzle,
} from "drizzle-orm/better-sqlite3";

import { runMigrations } from "./migrate";
import * as schema from "./schema";

const MIGRATIONS_FOLDER = path.resolve(__dirname, "migrations");

export interface TestDatabase {
  db: BetterSQLite3Database<typeof schema>;
  close: () => void;
}

export function createTestDb(): TestDatabase {
  const sqlite = new Database(":memory:");
  sqlite.pragma("foreign_keys = ON");

  const db = drizzle(sqlite, { schema, casing: "snake_case" });
  runMigrations(sqlite, MIGRATIONS_FOLDER);

  return {
    db,
    close: () => sqlite.close(),
  };
}
