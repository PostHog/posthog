import { describe, expect, it } from "vitest";
import { resumePiSessionInput, startPiSessionInput } from "./schemas";

describe("pi-session schemas", () => {
  it.each([
    [
      "start",
      startPiSessionInput,
      {
        taskContext: { taskId: "task-1", taskRunId: "run-1", cwd: "/w" },
        prompt: "hi",
      },
    ],
    [
      "resume",
      resumePiSessionInput,
      { taskContext: { taskId: "task-1", taskRunId: "run-1", cwd: "/w" } },
    ],
  ])("keeps the task run id through the %s input", (_label, schema, input) => {
    expect(schema.parse(input).taskContext.taskRunId).toBe("run-1");
  });
});
