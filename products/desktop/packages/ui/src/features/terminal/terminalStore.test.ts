import { beforeEach, describe, expect, it, vi } from "vitest";

const { removeScrollback, removeScrollbackForTask } = vi.hoisted(() => ({
  removeScrollback: vi.fn(),
  removeScrollbackForTask: vi.fn(),
}));

vi.mock("@posthog/ui/features/terminal/terminalScrollback", () => ({
  removeScrollback,
  removeScrollbackForTask,
}));

import { useTerminalStore } from "./terminalStore";

describe("terminalStore", () => {
  beforeEach(() => {
    localStorage.clear();
    removeScrollback.mockClear();
    removeScrollbackForTask.mockClear();
    useTerminalStore.setState({ terminalStates: {} });
  });

  it("keeps session and process state out of localStorage", () => {
    useTerminalStore.getState().setSessionId("task-1-shell", "shell-session");
    useTerminalStore.getState().setProcessName("task-1-shell", "vim");

    expect(localStorage.getItem("terminal-store")).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(useTerminalStore.getState().terminalStates["task-1-shell"]).toEqual({
      sessionId: "shell-session",
      processName: "vim",
    });
  });

  it("drops scrollback when a terminal state is cleared", () => {
    useTerminalStore.getState().setSessionId("task-1-shell", "shell-session");

    useTerminalStore.getState().clearTerminalState("task-1-shell");

    expect(removeScrollback).toHaveBeenCalledWith("task-1-shell");
    expect(
      useTerminalStore.getState().terminalStates["task-1-shell"],
    ).toBeUndefined();
  });

  it("drops scrollback for every terminal belonging to a task", () => {
    useTerminalStore.getState().setSessionId("task-1", "a");
    useTerminalStore.getState().setSessionId("task-1-shell", "b");
    useTerminalStore.getState().setSessionId("task-2-shell", "c");

    useTerminalStore.getState().clearTerminalStatesForTask("task-1");

    expect(removeScrollbackForTask).toHaveBeenCalledWith("task-1");
    expect(Object.keys(useTerminalStore.getState().terminalStates)).toEqual([
      "task-2-shell",
    ]);
  });
});
