import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { canControlTask } from "./taskControl";

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Task",
    description: "Description",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    origin_product: "user_created",
    ...overrides,
  };
}

describe("canControlTask", () => {
  it.each([
    {
      name: "allows a task author",
      task: makeTask({ channel: "channel-1" }),
      isTaskAuthor: true,
      expected: true,
    },
    {
      name: "allows a team-visible unchanneled task",
      task: makeTask({ origin_product: "signal_report" }),
      isTaskAuthor: false,
      expected: true,
    },
    {
      name: "denies a read-only unchanneled experiment task",
      task: makeTask({ origin_product: "experiments" }),
      isTaskAuthor: false,
      expected: false,
    },
    {
      name: "denies a read-only channel task",
      task: makeTask({
        channel: "channel-1",
        origin_product: "signal_report",
      }),
      isTaskAuthor: false,
      expected: false,
    },
  ])("$name", ({ task, isTaskAuthor, expected }) => {
    expect(canControlTask(task, isTaskAuthor)).toBe(expected);
  });
});
