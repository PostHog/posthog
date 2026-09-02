import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DatabaseService } from "../service";
import { createTestDb, type TestDatabase } from "../test-helpers";
import { AutoresearchRunRepository } from "./autoresearch-run-repository";

let testDb: TestDatabase;
let repo: AutoresearchRunRepository;

beforeEach(() => {
  testDb = createTestDb();
  const databaseService = { db: testDb.db } as unknown as DatabaseService;
  repo = new AutoresearchRunRepository(databaseService);
});

afterEach(() => {
  testDb.close();
});

const run = (overrides: Partial<Parameters<typeof repo.upsert>[0]> = {}) => ({
  id: "ar-1",
  taskId: "task-1",
  endedAt: null,
  data: '{"status":"running"}',
  ...overrides,
});

describe("AutoresearchRunRepository", () => {
  it("persists a run and reads it back by task", () => {
    repo.upsert(run());

    const rows = repo.findByTaskId("task-1");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      id: "ar-1",
      taskId: "task-1",
      endedAt: null,
      data: '{"status":"running"}',
    });
  });

  it("upserts in place on conflicting id", () => {
    repo.upsert(run());
    repo.upsert(
      run({ endedAt: "2026-07-02T00:00:00.000Z", data: '{"status":"done"}' }),
    );

    const rows = repo.findByTaskId("task-1");
    expect(rows).toHaveLength(1);
    expect(rows[0].endedAt).toBe("2026-07-02T00:00:00.000Z");
    expect(rows[0].data).toBe('{"status":"done"}');
  });

  it("findOpen returns only runs without an endedAt", () => {
    repo.upsert(run({ id: "ar-open-1" }));
    repo.upsert(run({ id: "ar-open-2", taskId: "task-2" }));
    repo.upsert(run({ id: "ar-done", endedAt: "2026-07-02T00:00:00.000Z" }));

    expect(repo.findOpen().map((r) => r.id)).toEqual([
      "ar-open-1",
      "ar-open-2",
    ]);
  });

  it("scopes findByTaskId to the task", () => {
    repo.upsert(run({ id: "ar-a", taskId: "task-a" }));
    repo.upsert(run({ id: "ar-b", taskId: "task-b" }));

    expect(repo.findByTaskId("task-a").map((r) => r.id)).toEqual(["ar-a"]);
    expect(repo.findByTaskId("task-none")).toEqual([]);
  });

  it("deleteByTaskId removes all of a task's runs", () => {
    repo.upsert(run({ id: "ar-a1" }));
    repo.upsert(run({ id: "ar-a2" }));
    repo.upsert(run({ id: "ar-b", taskId: "task-2" }));

    repo.deleteByTaskId("task-1");

    expect(repo.findByTaskId("task-1")).toEqual([]);
    expect(repo.findByTaskId("task-2")).toHaveLength(1);
  });
});
