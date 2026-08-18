import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";
import { TaskListView } from "./TaskListView";

const createTask = (
  id: string,
  title: string,
  lastActivityAt: number,
  isPinned: boolean,
): TaskData => ({
  id,
  title,
  createdAt: lastActivityAt,
  lastActivityAt,
  isGenerating: false,
  isUnread: false,
  isPinned,
  needsPermission: false,
  repository: null,
  isSuspended: false,
  folderPath: null,
  cloudPrUrl: null,
  branchName: null,
  linkedBranch: null,
});

const pinnedTasks = [
  createTask("pinned-1", "Polish the onboarding flow", 1_750_000_000_000, true),
  createTask(
    "pinned-2",
    "Investigate checkout errors",
    1_740_000_000_000,
    true,
  ),
];

const flatTasks = [
  createTask("task-1", "Add keyboard shortcuts", 1_730_000_000_000, false),
  createTask("task-2", "Improve dashboard loading", 1_720_000_000_000, false),
  createTask("task-3", "Update empty states", 1_710_000_000_000, false),
];

const meta = {
  title: "Sidebar/Task list drag and drop",
  component: TaskListView,
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => {
      useSidebarStore.setState({
        organizeMode: "chronological",
        sortMode: "updated",
      });
      return (
        <div className="h-[460px] w-72 overflow-hidden rounded-lg border border-gray-6 bg-gray-1 p-2">
          <Story />
        </div>
      );
    },
  ],
  args: {
    pinnedTasks,
    flatTasks,
    groupedTasks: [],
    activeTaskId: "task-2",
    editingTaskId: null,
    selectedTaskIds: [],
    onTaskClick: fn(),
    onTaskDoubleClick: fn(),
    onTaskContextMenu: fn(),
    onTaskArchive: fn(),
    onTaskTogglePin: fn(),
    onTaskEditSubmit: fn(),
    onTaskEditCancel: fn(),
    hasMore: false,
  },
} satisfies Meta<typeof TaskListView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
