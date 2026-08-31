import type { AgentSession } from "@posthog/shared";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";
import { sessionStoreSetters } from "../sessions/sessionStore";
import { UpdateInterruptDialog } from "./UpdateInterruptDialog";
import { useUpdateInterruptStore } from "./updateInterruptStore";

function workingSession(taskId: string, taskTitle: string): AgentSession {
  return {
    taskRunId: `run-${taskId}`,
    taskId,
    taskTitle,
    status: "connected",
    isPromptPending: true,
    pendingPermissions: new Map(),
    messageQueue: [],
    optimisticItems: [],
    events: [],
    startedAt: 0,
  } as AgentSession;
}

function SeededDialog({ sessions }: { sessions: AgentSession[] }) {
  useEffect(() => {
    sessionStoreSetters.clearAll();
    for (const session of sessions) sessionStoreSetters.setSession(session);
    useUpdateInterruptStore.getState().open(() => {});
    return () => {
      useUpdateInterruptStore.getState().clear();
      sessionStoreSetters.clearAll();
    };
  }, [sessions]);
  return <UpdateInterruptDialog />;
}

const meta: Meta<typeof SeededDialog> = {
  title: "Updates/UpdateInterruptDialog",
  component: SeededDialog,
};

export default meta;
type Story = StoryObj<typeof SeededDialog>;

export const OneTask: Story = {
  args: {
    sessions: [workingSession("t1", "Fix flaky signup test")],
  },
};

export const ThreeTasks: Story = {
  args: {
    sessions: [
      workingSession("t1", "Fix flaky signup test"),
      workingSession("t2", "Refactor billing webhooks"),
      workingSession("t3", "Write release notes for 0.23"),
    ],
  },
};
