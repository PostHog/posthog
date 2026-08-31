import type { AgentSession } from "@posthog/shared";
import { requestInstallUpdate } from "@posthog/ui/features/updates/installUpdateGuard";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { sessionStoreSetters } from "../sessions/sessionStore";
import { UpdateInterruptDialog } from "./UpdateInterruptDialog";
import { useUpdateInterruptStore } from "./updateInterruptStore";

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    children,
    onClick,
  }: PropsWithChildren<{ onClick?: () => void }>) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
}));

function makeSession(overrides: Partial<AgentSession>): AgentSession {
  return {
    taskRunId: `run-${overrides.taskId}`,
    taskId: "task",
    taskTitle: "Task title",
    status: "connected",
    isPromptPending: true,
    pendingPermissions: new Map(),
    messageQueue: [],
    optimisticItems: [],
    events: [],
    startedAt: 0,
    ...overrides,
  } as AgentSession;
}

describe("UpdateInterruptDialog", () => {
  beforeEach(() => {
    sessionStoreSetters.clearAll();
    useUpdateInterruptStore.setState({
      isOpen: false,
      waitingForIdle: false,
      runInstall: null,
    });
  });

  it("installs directly when no local agent is working", () => {
    sessionStoreSetters.setSession(
      makeSession({ taskId: "cloud", isCloud: true }),
    );
    sessionStoreSetters.setSession(
      makeSession({ taskId: "idle", isPromptPending: false }),
    );
    const runInstall = vi.fn();

    requestInstallUpdate(runInstall);

    expect(runInstall).toHaveBeenCalledOnce();
    expect(useUpdateInterruptStore.getState().isOpen).toBe(false);
  });

  it("lists the working local tasks and installs on restart now", () => {
    sessionStoreSetters.setSession(
      makeSession({ taskId: "t1", taskTitle: "Fix login flow", startedAt: 1 }),
    );
    sessionStoreSetters.setSession(
      makeSession({ taskId: "t2", taskTitle: "Write docs", startedAt: 2 }),
    );
    sessionStoreSetters.setSession(
      makeSession({ taskId: "cloud", taskTitle: "Cloud run", isCloud: true }),
    );
    const runInstall = vi.fn();

    render(<UpdateInterruptDialog />);
    act(() => requestInstallUpdate(runInstall));

    expect(runInstall).not.toHaveBeenCalled();
    expect(screen.getByText("Agents are still working")).toBeTruthy();
    expect(screen.getByText("Fix login flow")).toBeTruthy();
    expect(screen.getByText("Write docs")).toBeTruthy();
    expect(screen.queryByText("Cloud run")).toBeNull();

    fireEvent.click(screen.getByText("Restart now"));
    expect(runInstall).toHaveBeenCalledOnce();
    expect(useUpdateInterruptStore.getState().isOpen).toBe(false);
  });

  it("installs once the agents finish after restart when finished", () => {
    sessionStoreSetters.setSession(
      makeSession({ taskId: "t1", taskTitle: "Fix login flow" }),
    );
    const runInstall = vi.fn();

    render(<UpdateInterruptDialog />);
    act(() => requestInstallUpdate(runInstall));
    fireEvent.click(screen.getByText("Restart when finished"));

    expect(runInstall).not.toHaveBeenCalled();
    expect(useUpdateInterruptStore.getState().waitingForIdle).toBe(true);

    act(() =>
      sessionStoreSetters.updateSession("run-t1", { isPromptPending: false }),
    );

    expect(runInstall).toHaveBeenCalledOnce();
    expect(useUpdateInterruptStore.getState().waitingForIdle).toBe(false);
  });

  it("does not install after cancel even when the agents finish", () => {
    sessionStoreSetters.setSession(
      makeSession({ taskId: "t1", taskTitle: "Fix login flow" }),
    );
    const runInstall = vi.fn();

    render(<UpdateInterruptDialog />);
    act(() => requestInstallUpdate(runInstall));
    fireEvent.click(screen.getByText("Cancel"));
    act(() =>
      sessionStoreSetters.updateSession("run-t1", { isPromptPending: false }),
    );

    expect(runInstall).not.toHaveBeenCalled();
  });
});
