import { beforeEach, describe, expect, it, vi } from "vitest";

const startMutate = vi.fn(async (_input: Record<string, unknown>) => {});

vi.mock("@posthog/di/container", () => ({
  resolveService: () => ({ agent: { start: { mutate: startMutate } } }),
}));

vi.mock("../../shell/analytics", () => ({
  captureException: vi.fn(),
  track: vi.fn(),
}));

import { SetupRunServiceImpl } from "./setupRunServiceImpl";

describe("SetupRunServiceImpl.startAgent", () => {
  beforeEach(() => {
    startMutate.mockClear();
  });

  it("starts the discovery agent in plan mode, never bypassPermissions", async () => {
    const service = new SetupRunServiceImpl();

    await service.startAgent({
      taskId: "task-1",
      taskRunId: "run-1",
      repoPath: "/repo",
      apiHost: "https://us.posthog.com",
      projectId: 1,
      jsonSchema: {},
    });

    expect(startMutate).toHaveBeenCalledTimes(1);
    expect(startMutate.mock.calls[0][0]).toMatchObject({
      permissionMode: "plan",
      disallowedTools: ["EnterPlanMode", "ExitPlanMode", "AskUserQuestion"],
      settingSources: ["user"],
    });
  });
});
