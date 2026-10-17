import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/di/container", () => ({
  resolveService: vi.fn(),
}));

vi.mock("../../shell/analytics", () => ({
  track: vi.fn(),
  captureException: vi.fn(),
}));

const terminalMock = vi.hoisted(() => {
  type ExitListener = (event: { sessionId: string; exitCode?: number }) => void;
  const exitListeners = new Set<ExitListener>();
  return {
    exitListeners,
    terminalManager: {
      create: vi.fn(),
      on: vi.fn((_event: "exit", listener: ExitListener) => {
        exitListeners.add(listener);
        return () => exitListeners.delete(listener);
      }),
    },
  };
});

vi.mock("../terminal/TerminalManager", () => ({
  terminalManager: terminalMock.terminalManager,
}));

import { useActionStore } from "../actions/actionStore";
import { TrpcTaskCreationHost } from "./taskCreationHostImpl";

const args = {
  repoPath: "/repo",
  environmentId: "env-1",
  name: "Dev",
  script: "npm run setup",
};

describe("TrpcTaskCreationHost.confirmEnvironmentSetup", () => {
  const host = new TrpcTaskCreationHost();

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    { answer: true, expected: true },
    { answer: false, expected: false },
  ])(
    "returns $expected when the user answers $answer",
    async ({ answer, expected }) => {
      vi.spyOn(window, "confirm").mockReturnValue(answer);

      await expect(host.confirmEnvironmentSetup(args)).resolves.toBe(expected);
    },
  );

  it("prompts on every run so an earlier answer cannot be reused", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    await host.confirmEnvironmentSetup(args);
    await host.confirmEnvironmentSetup(args);

    expect(confirmSpy).toHaveBeenCalledTimes(2);
  });

  it("warns that the script can execute other files in the repository", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    await host.confirmEnvironmentSetup(args);

    expect(confirmSpy.mock.calls[0][0]).toContain(
      "can execute other files in the repository",
    );
  });
});

describe("TrpcTaskCreationHost.dispatchSetupAction", () => {
  const host = new TrpcTaskCreationHost();
  const dispatch = {
    taskId: "task-1",
    command: "npm run setup",
    cwd: "/worktree",
    label: "Setup: Dev",
  };

  const actionId = "setup-task-1-1000";

  beforeEach(() => {
    vi.spyOn(Date, "now").mockReturnValue(1000);
  });

  afterEach(() => {
    terminalMock.exitListeners.clear();
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("starts the script before the setup tab mounts", () => {
    host.dispatchSetupAction(dispatch);

    expect(terminalMock.terminalManager.create).toHaveBeenCalledWith(
      expect.objectContaining({
        command: "npm run setup",
        cwd: "/worktree",
        taskId: "task-1",
      }),
    );
  });

  it.each([
    { exitCode: 0, expected: "success" },
    { exitCode: 1, expected: "error" },
  ])(
    "sets status $expected when the script exits with $exitCode",
    ({ exitCode, expected }) => {
      host.dispatchSetupAction(dispatch);
      expect(useActionStore.getState().statuses[actionId]).toBe("running");

      for (const listener of terminalMock.exitListeners) {
        listener({ sessionId: `action-${actionId}-0`, exitCode });
      }

      expect(useActionStore.getState().statuses[actionId]).toBe(expected);
    },
  );
});
