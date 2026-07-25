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
  /** Age of the task's last activity, resolved to a timestamp at render. */
  ageHours: number;
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
  // Ages become timestamps here rather than in `args`, so the relative labels
  // are read off the same clock that renders them. The visual-regression runner
  // freezes the clock in a decorator (apps/code/.storybook/preview.tsx) while
  // story args are evaluated at import time against the real one — anchoring
  // args to `Date.now()` collapses every label to "now" in CI.
  const now = Date.now();
  return (
    <div className="flex w-[280px] flex-col bg-gray-2 py-1">
      {sectionLabel ? (
        <MenuLabel className="flex items-center py-0">{sectionLabel}</MenuLabel>
      ) : null}
      {rows.map(({ ageHours, ...row }) => (
        <TaskItem
          key={row.taskId}
          {...row}
          timestamp={now - ageHours * HOUR}
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
        ageHours: 1,
        workspaceMode: "cloud",
        taskRunStatus: "completed",
      },
      {
        taskId: "t2",
        label: "Implement btw command in PostHog Code",
        ageHours: 26,
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
        ageHours: 0,
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
        ageHours: 3,
        isPinned: true,
        prState: "open",
      },
      {
        taskId: "p3",
        label: "Add disable-model-invocation support to Desktop skills",
        subtitle: context({ repository: CODE_REPO, workspaceMode: "cloud" }),
        ageHours: 27,
        isPinned: true,
        workspaceMode: "cloud",
        taskRunStatus: "completed",
      },
      {
        taskId: "p4",
        label: "Scan prod for affected teams",
        subtitle: context({}),
        ageHours: 30,
        isPinned: true,
      },
    ],
  },
};
