import type { Meta, StoryObj } from "@storybook/react-vite";
import { VoiceToolActivity } from "./VoiceToolActivity";

const meta = {
  title: "Sessions/Voice tool activity",
  component: VoiceToolActivity,
  decorators: [
    (Story) => (
      <div className="w-96">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof VoiceToolActivity>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Answers: Story = {
  args: {
    calls: [
      {
        id: "task",
        name: "send_to_task",
        input: "Help me plan a demo app.",
        status: "running",
      },
      {
        id: "answer",
        name: "answer_question",
        input: "Which platform should the demo use?",
        result: "Web",
        status: "completed",
      },
    ],
  },
};
export const Failed: Story = {
  args: {
    calls: [
      {
        id: "failed",
        name: "answer_question",
        input: "Which platform should the demo use?",
        result: "Answer was not recorded. Try again.",
        status: "failed",
      },
    ],
  },
};
