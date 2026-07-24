import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { runMigrations } from "./migrate";

const MIGRATIONS_FOLDER = path.resolve(__dirname, "migrations");

const MID_HISTORY_ADD_COLUMN_TIMESTAMP = 1782781314961;

let sqlite: InstanceType<typeof Database>;

beforeEach(() => {
  sqlite = new Database(":memory:");
  sqlite.pragma("foreign_keys = ON");
});

afterEach(() => {
  sqlite.close();
});

function ledgerMax(db: InstanceType<typeof Database>): number | null {
  const row = db
    .prepare("SELECT MAX(created_at) AS max FROM __drizzle_migrations")
    .get() as { max: number | null };
  return row.max;
}

function ledgerHas(
  db: InstanceType<typeof Database>,
  timestamp: number,
): boolean {
  const row = db
    .prepare(
      "SELECT COUNT(*) AS count FROM __drizzle_migrations WHERE created_at = ?",
    )
    .get(timestamp) as { count: number };
  return row.count > 0;
}

function hasColumn(
  db: InstanceType<typeof Database>,
  table: string,
  column: string,
): boolean {
  return db
    .prepare(`PRAGMA table_info(${table})`)
    .all()
    .some((c) => (c as { name: string }).name === column);
}

describe("runMigrations", () => {
  it("applies every migration on a fresh database", () => {
    runMigrations(sqlite, MIGRATIONS_FOLDER);

    expect(hasColumn(sqlite, "workspaces", "pr_urls")).toBe(true);
    expect(ledgerMax(sqlite)).not.toBeNull();
  });

  it("is a no-op when run twice", () => {
    runMigrations(sqlite, MIGRATIONS_FOLDER);
    const afterFirst = ledgerMax(sqlite);

    expect(() => runMigrations(sqlite, MIGRATIONS_FOLDER)).not.toThrow();
    expect(ledgerMax(sqlite)).toBe(afterFirst);
  });

  it("boots when the schema is already ahead of the migration ledger", () => {
    runMigrations(sqlite, MIGRATIONS_FOLDER);
    const latest = ledgerMax(sqlite);

    sqlite
      .prepare("DELETE FROM __drizzle_migrations WHERE created_at = ?")
      .run(latest);
    expect(ledgerMax(sqlite)).not.toBe(latest);

    expect(() => runMigrations(sqlite, MIGRATIONS_FOLDER)).not.toThrow();
    expect(hasColumn(sqlite, "workspaces", "pr_urls")).toBe(true);
    expect(ledgerMax(sqlite)).toBe(latest);
  });

  it("re-applies a missing mid-history ledger entry", () => {
    runMigrations(sqlite, MIGRATIONS_FOLDER);

    sqlite
      .prepare("DELETE FROM __drizzle_migrations WHERE created_at = ?")
      .run(MID_HISTORY_ADD_COLUMN_TIMESTAMP);
    expect(ledgerHas(sqlite, MID_HISTORY_ADD_COLUMN_TIMESTAMP)).toBe(false);

    expect(() => runMigrations(sqlite, MIGRATIONS_FOLDER)).not.toThrow();
    expect(ledgerHas(sqlite, MID_HISTORY_ADD_COLUMN_TIMESTAMP)).toBe(true);
  });

  it("propagates errors other than duplicate-column conflicts", () => {
    const dir = writeTempMigration("DROP TABLE `table_that_does_not_exist`;");
    try {
      expect(() => runMigrations(sqlite, dir)).toThrow(/no such table/i);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("does not swallow an 'already exists' conflict from a new migration", () => {
    sqlite.exec("CREATE TABLE existing_table (id text)");
    const dir = writeTempMigration(
      "CREATE TABLE `existing_table` (`id` text);",
    );
    try {
      expect(() => runMigrations(sqlite, dir)).toThrow(/already exists/i);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  // 0013 was amended in place on the bluebird branch, so dogfood DBs have it
  // recorded as applied while carrying an earlier variant of the browser-tabs
  // schema. 0020 must heal every observed variant without ever failing boot.
  describe("0020 browser-tabs repair", () => {
    const REPAIR_TIMESTAMP = 1783685997328;

    function markHistoryApplied(db: InstanceType<typeof Database>) {
      // Record 0000..0019 as applied without running them, mimicking a DB
      // whose ledger is ahead of its real schema.
      db.exec(
        "CREATE TABLE IF NOT EXISTS __drizzle_migrations (id SERIAL PRIMARY KEY, hash text NOT NULL, created_at numeric)",
      );
      const journal = JSON.parse(
        readFileSync(
          path.join(MIGRATIONS_FOLDER, "meta", "_journal.json"),
          "utf8",
        ),
      ) as { entries: { idx: number; when: number }[] };
      const insert = db.prepare(
        "INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('x', ?)",
      );
      for (const entry of journal.entries) {
        if (entry.when !== REPAIR_TIMESTAMP) insert.run(entry.when);
      }
    }

    it("heals the panes-era variant (tables exist, active_tab_id missing)", () => {
      markHistoryApplied(sqlite);
      sqlite.exec(`
        CREATE TABLE browser_windows (id text PRIMARY KEY NOT NULL,
          is_primary integer DEFAULT false NOT NULL, bounds text,
          position integer DEFAULT 0 NOT NULL, created_at integer NOT NULL,
          updated_at integer NOT NULL, layout text, focused_pane_id text);
        CREATE TABLE browser_tabs (id text PRIMARY KEY NOT NULL,
          window_id text NOT NULL, dashboard_id text, channel_id text,
          position integer NOT NULL, scroll_state text,
          created_at integer NOT NULL, last_active_at integer NOT NULL,
          pane_id text);
      `);

      expect(() => runMigrations(sqlite, MIGRATIONS_FOLDER)).not.toThrow();
      expect(hasColumn(sqlite, "browser_windows", "active_tab_id")).toBe(true);
      expect(hasColumn(sqlite, "browser_tabs", "task_id")).toBe(true);
      expect(hasColumn(sqlite, "browser_tabs", "channel_section")).toBe(true);
      expect(hasColumn(sqlite, "browser_tabs", "app_view")).toBe(true);
    });

    it("heals a variant missing the browser tables entirely", () => {
      markHistoryApplied(sqlite);

      expect(() => runMigrations(sqlite, MIGRATIONS_FOLDER)).not.toThrow();
      expect(hasColumn(sqlite, "browser_windows", "active_tab_id")).toBe(true);
      expect(hasColumn(sqlite, "browser_tabs", "app_view")).toBe(true);
    });

    it("tolerates arbitrary statement failures in a best-effort migration", () => {
      // An unforeseen divergence must degrade to "still broken", never a
      // failed migration batch that kills boot.
      markHistoryApplied(sqlite);
      // A browser_windows table that can't accept the ALTERs cleanly: the
      // column exists with a different type — ALTER throws duplicate column
      // (tolerated), and the CREATEs no-op. Simulate a nastier case by making
      // browser_tabs a VIEW, which CREATE TABLE IF NOT EXISTS *and* ALTER
      // both reject with non-duplicate-column errors.
      sqlite.exec(`
        CREATE TABLE browser_windows (id text PRIMARY KEY NOT NULL,
          is_primary integer DEFAULT false NOT NULL, bounds text,
          active_tab_id text, position integer DEFAULT 0 NOT NULL,
          created_at integer NOT NULL, updated_at integer NOT NULL);
        CREATE VIEW browser_tabs AS SELECT 1 AS id;
      `);

      expect(() => runMigrations(sqlite, MIGRATIONS_FOLDER)).not.toThrow();
      expect(ledgerHas(sqlite, REPAIR_TIMESTAMP)).toBe(true);
    });
  });
});

function writeTempMigration(sql: string): string {
  const dir = mkdtempSync(path.join(tmpdir(), "migrate-test-"));
  mkdirSync(path.join(dir, "meta"), { recursive: true });
  writeFileSync(
    path.join(dir, "meta", "_journal.json"),
    JSON.stringify({
      version: "7",
      dialect: "sqlite",
      entries: [
        { idx: 0, version: "6", when: 1, tag: "0000_temp", breakpoints: true },
      ],
    }),
  );
  writeFileSync(path.join(dir, "0000_temp.sql"), sql);
  return dir;
}
