import {
  TaskStatusDot,
  TaskStatusTooltips,
} from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import {
  type TaskDot,
  type TaskStatusInput,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { LogoMark } from "@posthog/ui/primitives/LogoMark";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof TaskStatusDot> = {
  title: "Components/Sidebar/TaskStatusDot",
  component: TaskStatusDot,
  parameters: { layout: "centered" },
};

export default meta;
type Story = StoryObj<typeof TaskStatusDot>;

/**
 * Every state the vocabulary produces, driven through `taskDot` itself so the
 * story can't drift from the real mapping. Hover a mark for its label.
 */
const ROWS: { title: string; input: TaskStatusInput }[] = [
  { title: "Agent generating", input: { isGenerating: true } },
  {
    title: "Cloud run starting",
    input: { taskRunStatus: "queued", workspaceMode: "cloud" },
  },
  { title: "Needs permission", input: { needsPermission: true } },
  { title: "Unread output", input: { isUnread: true } },
  { title: "Run claims work", input: { taskRunStatus: "in_progress" } },
  { title: "All caught up", input: {} },
  { title: "Suspended", input: { isSuspended: true } },
];

// The delete-undo state ChannelItemRow builds directly rather than through
// taskDot — kept in the story so the red pulse is reviewed with the rest.
const DELETING_DOT: TaskDot = {
  tone: "red",
  style: "solid",
  pulse: true,
  label: "Deleting…",
};

function Row({ dot, title }: { dot: TaskDot; title: string }) {
  return (
    <div className="flex items-center gap-2 rounded px-2 py-1.5 text-[13px]">
      <TaskStatusDot dot={dot} />
      <span className="truncate">{title}</span>
    </div>
  );
}

export const AllStates: Story = {
  render: () => (
    <TaskStatusTooltips>
      <div className="flex w-64 flex-col">
        {ROWS.map(({ title, input }) => (
          <Row key={title} dot={taskDot(input)} title={title} />
        ))}
        <Row dot={DELETING_DOT} title="Deleting canvas…" />
      </div>
    </TaskStatusTooltips>
  ),
};

/** The spike wave at row size and zoomed, for judging the motion itself. */
export const WorkingWave: Story = {
  render: () => (
    <div className="flex items-end gap-8" style={{ color: "var(--primary)" }}>
      <LogoMark width={15} wave />
      <LogoMark width={36} wave />
      <LogoMark width={96} wave />
    </div>
  ),
};
