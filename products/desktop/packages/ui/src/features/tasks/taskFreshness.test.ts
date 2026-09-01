import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { pickFreshestTask } from "./taskFreshness";

function makeTask(
  title: string,
  updatedAt: string,
  runUpdatedAt?: string,
): Task {
  return {
    id: title,
    task_number: 1,
    slug: title,
    title,
    description: "",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: updatedAt,
    origin_product: "user_created",
    latest_run: runUpdatedAt
      ? ({
          id: `${title}-run`,
          updated_at: runUpdatedAt,
        } as Task["latest_run"])
      : undefined,
  };
}

describe("pickFreshestTask", () => {
  it("prefers the first task when timestamps tie", () => {
    const detail = makeTask("detail", "2026-01-01T00:00:00.000Z");
    const list = makeTask("list", "2026-01-01T00:00:00.000Z");

    expect(pickFreshestTask(detail, list)).toBe(detail);
  });

  it("uses latest run activity when it is newer than the task", () => {
    const completedDetail = makeTask(
      "detail",
      "2026-01-01T00:00:00.000Z",
      "2026-01-01T00:05:00.000Z",
    );
    const staleList = makeTask(
      "list",
      "2026-01-01T00:03:00.000Z",
      "2026-01-01T00:03:00.000Z",
    );

    expect(pickFreshestTask(staleList, completedDetail)).toBe(completedDetail);
  });

  it("keeps a newer list update when it arrives after detail data", () => {
    const detail = makeTask(
      "detail",
      "2026-01-01T00:00:00.000Z",
      "2026-01-01T00:05:00.000Z",
    );
    const newerList = makeTask(
      "list",
      "2026-01-01T00:06:00.000Z",
      "2026-01-01T00:06:00.000Z",
    );

    expect(pickFreshestTask(detail, newerList)).toBe(newerList);
  });
});
