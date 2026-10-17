import { UserMessageBody } from "@posthog/ui/features/sessions/components/chat-thread/UserMessageBody";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Sessions/Voice message",
  component: UserMessageBody,
  decorators: [
    (Story) => (
      <div className="w-full max-w-lg rounded-lg bg-muted p-3 text-sm">
        <Story />
      </div>
    ),
  ],
  args: {
    content:
      "Spoken conversation:\nUser: Check the build.\nVoice assistant: Which branch should I check?\nUser: Check the current branch and summarize any failures.",
  },
} satisfies Meta<typeof UserMessageBody>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Collapsed: Story = {};
export const SingleRequest: Story = {
  args: { content: "Spoken conversation:\nUser: Explain the latest change." },
};
export const Narrow: Story = {
  decorators: [
    (Story) => (
      <div className="w-64">
        <Story />
      </div>
    ),
  ],
};
