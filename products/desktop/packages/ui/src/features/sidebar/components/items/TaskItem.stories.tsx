import {
  formatTaskContext,
  type TaskContextTask,
} from "@posthog/core/sidebar/taskContext";
import { MenuLabel } from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { TaskItem } from "./TaskItem";

const HOUR = 3_600_000;

const CODE_REPO = {
  fullPath: "posthog/code",
  name: "code",
  organization: "PostHog",
};
const POSTHOG_REPO = {
  fullPath: "posthog/posthog",
  name: "posthog",
  organization: "PostHog",
};

/** The context line exactly as the sidebar builds it for a pinned row. */
function context(task: Partial<TaskContextTask>): string | undefined {
  return (
    formatTaskContext({
      repository: null,
      branchName: null,
      linkedBranch: null,
      ...task,
    }) ?? undefined
  );
}

interface Row {
  taskId: string;
  label: string;
  subtitle?: string;
  timestamp: number;
  isPinned?: boolean;
  workspaceMode?: "local" | "worktree" | "cloud";
  taskRunStatus?: "completed";
  prState?: "open";
}

const noop = () => {};

function TaskRows({
  rows,
  sectionLabel,
}: {
  rows: Row[];
  sectionLabel?: string;
}) {
  return (
    <div className="flex w-[280px] flex-col bg-gray-2 py-1">
      {sectionLabel ? (
        <MenuLabel className="flex items-center py-0">{sectionLabel}</MenuLabel>
      ) : null}
      {rows.map((row) => (
        <TaskItem
          key={row.taskId}
          {...row}
          isActive={false}
          onClick={noop}
          onContextMenu={noop}
          onArchive={noop}
          onTogglePin={noop}
        />
      ))}
    </div>
  );
}

const meta: Meta<typeof TaskRows> = {
  title: "Sidebar/TaskItem",
  component: TaskRows,
  decorators: [
    (Story) => (
      <div style={{ margin: "2rem" }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof TaskRows>;

/**
 * A row inside a repository group: one line, because the group header above it
 * already says which repository the task belongs to.
 */
export const InRepositoryGroup: Story = {
  args: {
    sectionLabel: "code",
    rows: [
      {
        taskId: "t1",
        label: "Implement /clear command for PostHog Code",
        timestamp: Date.now() - HOUR,
        workspaceMode: "cloud",
        taskRunStatus: "completed",
      },
      {
        taskId: "t2",
        label: "Implement btw command in PostHog Code",
        timestamp: Date.now() - 26 * HOUR,
        workspaceMode: "worktree",
        prState: "open",
      },
    ],
  },
};

/**
 * The pinned section floats above every repository group, so each row carries
 * its own `repository · branch` context line.
 */
export const Pinned: Story = {
  args: {
    sectionLabel: "Pinned",
    rows: [
      {
        taskId: "p1",
        label: "Write runbook for /local_evaluation 5xx errors",
        subtitle: context({
          repository: POSTHOG_REPO,
          workspaceMode: "worktree",
          branchName: "haacked/local-eval-runbook",
        }),
        timestamp: Date.now(),
        isPinned: true,
        workspaceMode: "worktree",
      },
      {
        taskId: "p2",
        label: "PostHog Desktop command line unattended mode",
        subtitle: context({
          repository: CODE_REPO,
          workspaceMode: "local",
          branchName: "main",
          linkedBranch: "posthog-code/unattended-mode",
        }),
        timestamp: Date.now() - 3 * HOUR,
        isPinned: true,
        prState: "open",
      },
      {
        taskId: "p3",
        label: "Add disable-model-invocation support to Desktop skills",
        subtitle: context({ repository: CODE_REPO, workspaceMode: "cloud" }),
        timestamp: Date.now() - 27 * HOUR,
        isPinned: true,
        workspaceMode: "cloud",
        taskRunStatus: "completed",
      },
      {
        taskId: "p4",
        label: "Scan prod for affected teams",
        subtitle: context({}),
        timestamp: Date.now() - 30 * HOUR,
        isPinned: true,
      },
    ],
  },
};
