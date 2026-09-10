import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  destroyForTask: vi.fn(),
  clearTerminalStatesForTask: vi.fn(),
}));

vi.mock("./TerminalManager", () => ({
  terminalManager: { destroyForTask: mocks.destroyForTask },
}));

vi.mock("./terminalStore", () => ({
  useTerminalStore: {
    getState: () => ({
      clearTerminalStatesForTask: mocks.clearTerminalStatesForTask,
    }),
  },
}));

import { destroyTaskTerminals } from "./destroyTaskTerminals";

describe("destroyTaskTerminals", () => {
  it("destroys live instances and clears persisted state for the task", () => {
    destroyTaskTerminals("task-1");

    expect(mocks.destroyForTask).toHaveBeenCalledWith("task-1");
    expect(mocks.clearTerminalStatesForTask).toHaveBeenCalledWith("task-1");
  });
});
