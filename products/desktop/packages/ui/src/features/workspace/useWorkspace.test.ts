import type { Workspace } from "@posthog/shared";
import type { Task, TaskRunEnvironment } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { isCloudTask } from "./useWorkspace";

function task(environment?: TaskRunEnvironment): Task {
  return {
    id: "task-1",
    ...(environment ? { latest_run: { environment } } : {}),
  } as Task;
}

function workspace(mode: Workspace["mode"]): Workspace {
  return { mode } as Workspace;
}

describe("isCloudTask", () => {
  it.each([
    {
      name: "no workspace row, cloud run",
      task: task("cloud"),
      workspace: null,
      expected: true,
    },
    {
      name: "no workspace row, local run",
      task: task("local"),
      workspace: null,
      expected: false,
    },
    {
      name: "no workspace row, no run",
      task: task(),
      workspace: null,
      expected: false,
    },
    {
      name: "cloud workspace row",
      task: task(),
      workspace: workspace("cloud"),
      expected: true,
    },
    {
      name: "local workspace row wins over cloud run",
      task: task("cloud"),
      workspace: workspace("local"),
      expected: false,
    },
    {
      name: "worktree workspace row wins over cloud run",
      task: task("cloud"),
      workspace: workspace("worktree"),
      expected: false,
    },
  ])("$name -> $expected", ({ task, workspace, expected }) => {
    expect(isCloudTask(task, workspace)).toBe(expected);
  });
});
