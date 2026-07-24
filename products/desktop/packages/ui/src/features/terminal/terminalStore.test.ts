import { beforeEach, describe, expect, it, vi } from "vitest";

const { managerOn } = vi.hoisted(() => ({
  managerOn: vi.fn(() => vi.fn()),
}));

vi.mock("./TerminalManager", () => ({
  terminalManager: {
    on: managerOn,
  },
}));

import { clearPersistedSessionIds, useTerminalStore } from "./terminalStore";

describe("terminalStore persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    managerOn.mockClear();
    useTerminalStore.setState({
      terminalStates: {},
    });
  });

  it("does not persist process-local shell session ids", () => {
    useTerminalStore
      .getState()
      .setSerializedState("task-1-shell", "scrollback");
    useTerminalStore
      .getState()
      .setSessionId("task-1-shell", "shell-stale-session");

    const persisted = JSON.parse(localStorage.getItem("terminal-store") ?? "");

    expect(persisted.state.terminalStates["task-1-shell"]).toEqual({
      serializedState: "scrollback",
      sessionId: null,
    });
  });

  it("clears session ids from old persisted terminal state", () => {
    expect(
      clearPersistedSessionIds({
        terminalStates: {
          "task-1-shell": {
            serializedState: "scrollback",
            sessionId: "shell-stale-session",
          },
        },
      }),
    ).toEqual({
      terminalStates: {
        "task-1-shell": {
          serializedState: "scrollback",
          sessionId: null,
        },
      },
    });
  });
});
