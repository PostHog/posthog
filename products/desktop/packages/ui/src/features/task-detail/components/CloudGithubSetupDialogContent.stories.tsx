import { Button } from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { CloudGithubSetupDialogContent } from "./CloudGithubSetupDialogContent";

const meta = {
  title: "Task detail/Cloud GitHub setup",
  component: CloudGithubSetupDialogContent,
  args: {
    connected: false,
    loading: false,
    hasError: false,
    isTimedOut: false,
    canConnect: true,
    onConnect: () => {},
    onOpenPermissions: () => {},
    onClose: () => {},
  },
} satisfies Meta<typeof CloudGithubSetupDialogContent>;

export default meta;
type Story = StoryObj<typeof meta>;

export const GitHubRequired: Story = {};

export const WaitingForGitHub: Story = {
  args: { loading: true },
};

export const OpenFromButton: Story = {
  render: function Render(args) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Open GitHub setup</Button>
        {open && (
          <CloudGithubSetupDialogContent
            {...args}
            onClose={() => setOpen(false)}
          />
        )}
      </>
    );
  },
};
