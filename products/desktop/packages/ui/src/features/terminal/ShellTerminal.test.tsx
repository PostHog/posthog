import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { renderSpy } = vi.hoisted(() => ({ renderSpy: vi.fn() }));

vi.mock("./Terminal", () => ({
  Terminal: (props: Record<string, unknown>) => {
    renderSpy(props);
    return null;
  },
}));

vi.mock("@posthog/ui/features/terminal/terminalScrollback", () => ({
  removeScrollback: vi.fn(),
  removeScrollbackForTask: vi.fn(),
}));

import { ShellTerminal } from "./ShellTerminal";
import { useTerminalStore } from "./terminalStore";

describe("ShellTerminal", () => {
  beforeEach(() => {
    renderSpy.mockClear();
    useTerminalStore.setState({ terminalStates: {} });
  });

  it("does not pass scrollback through React props", () => {
    render(<ShellTerminal stateKey="task-1-shell" cwd="/repo" />);

    expect(renderSpy).toHaveBeenCalled();
    expect(renderSpy.mock.calls[0][0]).not.toHaveProperty("initialState");
    expect(renderSpy.mock.calls[0][0]).toMatchObject({
      persistenceKey: "task-1-shell",
      cwd: "/repo",
    });
  });

  it("does not re-render when unrelated terminal state changes", () => {
    render(<ShellTerminal stateKey="task-1-shell" cwd="/repo" />);
    const initialRenders = renderSpy.mock.calls.length;

    act(() => {
      useTerminalStore.getState().setProcessName("task-2-shell", "vim");
      useTerminalStore.getState().setSessionId("task-2-shell", "other-session");
    });

    expect(renderSpy.mock.calls.length).toBe(initialRenders);
  });

  it("does not re-render when its own process name changes", () => {
    render(<ShellTerminal stateKey="task-1-shell" cwd="/repo" />);
    const initialRenders = renderSpy.mock.calls.length;

    act(() => {
      useTerminalStore.getState().setProcessName("task-1-shell", "vim");
    });

    expect(renderSpy.mock.calls.length).toBe(initialRenders);
  });
});
