import type { Meta, StoryObj } from "@storybook/react-vite";
import { LocalChangesDialog } from "./LocalChangesDialog";

const meta: Meta<typeof LocalChangesDialog> = {
  title: "Task detail/Local changes dialog",
  component: LocalChangesDialog,
  parameters: { layout: "centered" },
  args: {
    open: true,
    stagedFiles: ["packages/ui/src/features/tasks/TaskList.tsx"],
    unstagedFiles: ["packages/core/src/tasks/taskService.ts"],
    untrackedFiles: ["packages/ui/src/features/tasks/NewTask.tsx"],
    isStashing: false,
    stashError: null,
    onOpenChange: () => {},
    onCancel: () => {},
    onContinue: () => {},
    onStashAndContinue: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof LocalChangesDialog>;

export const Default: Story = {};

export const StashFailed: Story = {
  args: {
    stashError: "Could not stash local changes. Check Git, then try again.",
  },
};
