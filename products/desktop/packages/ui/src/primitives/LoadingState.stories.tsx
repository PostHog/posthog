import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Primitives/LoadingState",
  component: LoadingState,
  decorators: [
    (Story) => (
      <div className="h-64 w-96 rounded-md border border-gray-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof LoadingState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const WithLabel: Story = {
  args: { label: "Loading archived tasks..." },
};
