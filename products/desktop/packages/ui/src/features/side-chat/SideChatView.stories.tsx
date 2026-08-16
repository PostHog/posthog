import { SideChatView } from "@posthog/ui/features/side-chat/SideChatView";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof SideChatView> = {
  title: "Features/Side chat/SideChatView",
  component: SideChatView,
  decorators: [
    (Story) => (
      <div className="h-screen w-full max-w-xl border border-border">
        <Story />
      </div>
    ),
  ],
  args: {
    taskId: "task-1",
    question: "",
    onQuestionChange: () => {},
    onSubmit: (event) => event.preventDefault(),
  },
};

export default meta;
type Story = StoryObj<typeof SideChatView>;

export const Empty: Story = {
  args: {
    thread: { messages: [], isLoading: false, hasError: false },
  },
};

export const Conversation: Story = {
  args: {
    thread: {
      messages: [
        {
          id: "question-1",
          role: "user",
          content: "Why does the plan separate the migration into two steps?",
        },
        {
          id: "answer-1",
          role: "assistant",
          content:
            "The first step keeps the old and new fields compatible. The second removes the old field after all callers have moved over.",
        },
      ],
      isLoading: false,
      hasError: false,
    },
  },
};

export const Answering: Story = {
  args: {
    question: "Could we combine them?",
    thread: {
      messages: [
        {
          id: "question-1",
          role: "user",
          content: "What is the main risk in this plan?",
        },
      ],
      isLoading: true,
      hasError: false,
    },
  },
};
