import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DatabaseService } from "../service";
import { createTestDb, type TestDatabase } from "../test-helpers";
import {
  ClaudeSessionImportRepository,
  type RecordClaudeSessionImportData,
} from "./claude-session-import-repository";

let testDb: TestDatabase;
let imports: ClaudeSessionImportRepository;

beforeEach(() => {
  testDb = createTestDb();
  const databaseService = { db: testDb.db } as unknown as DatabaseService;
  imports = new ClaudeSessionImportRepository(databaseService);
});

afterEach(() => {
  testDb.close();
});

const importData = (
  overrides: Partial<RecordClaudeSessionImportData> = {},
): RecordClaudeSessionImportData => ({
  sourceSessionId: "5e4f5423-0287-4473-ae06-24df41c62993",
  importedSessionId: crypto.randomUUID(),
  taskId: "task-1",
  repoPath: "/repos/twig",
  sourceMtimeMs: 1_700_000_000_000,
  sourceSizeBytes: 4096,
  sourceLastEntryUuid: "entry-uuid-1",
  ...overrides,
});

describe("ClaudeSessionImportRepository", () => {
  it("records an import and reads it back by task id", () => {
    const created = imports.recordImport(importData());

    const found = imports.findByTaskId("task-1");

    expect(found?.id).toBe(created.id);
    expect(found?.sourceSessionId).toBe("5e4f5423-0287-4473-ae06-24df41c62993");
    expect(found?.sourceMtimeMs).toBe(1_700_000_000_000);
    expect(found?.sourceSizeBytes).toBe(4096);
    expect(found?.sourceLastEntryUuid).toBe("entry-uuid-1");
  });

  it("lists imports for the requested source session ids only", () => {
    imports.recordImport(importData({ taskId: "task-1" }));
    imports.recordImport(
      importData({ sourceSessionId: "other-source", taskId: "task-2" }),
    );

    const rows = imports.listBySourceSessionIds([
      "5e4f5423-0287-4473-ae06-24df41c62993",
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0]?.taskId).toBe("task-1");
  });

  it("returns an empty list for no source session ids", () => {
    imports.recordImport(importData());

    expect(imports.listBySourceSessionIds([])).toEqual([]);
  });

  it("allows multiple imports of the same source under distinct imported ids", () => {
    imports.recordImport(importData({ taskId: "task-1" }));
    imports.recordImport(importData({ taskId: "task-2" }));

    const rows = imports.listBySourceSessionIds([
      "5e4f5423-0287-4473-ae06-24df41c62993",
    ]);

    expect(rows).toHaveLength(2);
  });

  it("orders same-second imports of one source newest first", () => {
    // Both rows share a CURRENT_TIMESTAMP second; the rowid tiebreak must still
    // put the later insert first so the service reads the latest import.
    imports.recordImport(importData({ taskId: "task-1" }));
    imports.recordImport(importData({ taskId: "task-2" }));

    const rows = imports.listBySourceSessionIds([
      "5e4f5423-0287-4473-ae06-24df41c62993",
    ]);

    expect(rows.map((r) => r.taskId)).toEqual(["task-2", "task-1"]);
  });

  it("rejects duplicate imported session ids", () => {
    const data = importData();
    imports.recordImport(data);

    expect(() => imports.recordImport({ ...data, taskId: "task-2" })).toThrow();
  });

  it("deletes imports by task id, leaving others intact", () => {
    imports.recordImport(importData({ taskId: "task-1" }));
    imports.recordImport(
      importData({ sourceSessionId: "other-source", taskId: "task-2" }),
    );

    imports.deleteByTaskId("task-1");

    expect(imports.findByTaskId("task-1")).toBeNull();
    expect(imports.findByTaskId("task-2")).not.toBeNull();
  });

  it("deletes an import by imported session id, leaving others intact", () => {
    const target = importData({ taskId: "task-1" });
    imports.recordImport(target);
    imports.recordImport(
      importData({ sourceSessionId: "other-source", taskId: "task-2" }),
    );

    imports.deleteByImportedSessionId(target.importedSessionId);

    expect(imports.findByTaskId("task-1")).toBeNull();
    expect(imports.findByTaskId("task-2")).not.toBeNull();
  });

  it("deletes nothing when no row matches the imported session id", () => {
    imports.recordImport(importData({ taskId: "task-1" }));

    imports.deleteByImportedSessionId(crypto.randomUUID());

    expect(imports.findByTaskId("task-1")).not.toBeNull();
  });
});
