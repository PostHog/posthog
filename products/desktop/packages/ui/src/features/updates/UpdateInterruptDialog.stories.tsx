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
    isCompacting: false,
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

// A task carries its raw prompt as a title until one is generated, which is the
// same window this dialog catches.
const RAW_PROMPT =
  "The signup form accepts an email the backend later rejects, so people land " +
  "on a blank screen with no way back. Reproduce it, find where the two " +
  "validations disagree, and make them agree.";

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

// The two unbounded spots, on a window short enough to clip: one raw prompt
// inline in the description, and a full list of them.
export const OneRawPromptTitle: Story = {
  args: {
    sessions: [workingSession("t1", RAW_PROMPT)],
  },
};

export const ManyLongTitles: Story = {
  args: {
    sessions: Array.from({ length: 10 }, (_, index) =>
      workingSession(`t${index}`, `${RAW_PROMPT} (${index + 1})`),
    ),
  },
};
