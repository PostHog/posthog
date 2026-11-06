import { Button } from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Primitives/Spinner",
  component: Spinner,
  parameters: { layout: "centered" },
} satisfies Meta<typeof Spinner>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Sizes: Story = {
  render: () => (
    <div className="flex items-center gap-4 text-gray-11">
      <Spinner size="xs" />
      <Spinner size="sm" />
      <Spinner size="md" />
      <Spinner size="lg" />
    </div>
  ),
};

export const InButtons: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Button size="xs">
        <Spinner /> Saving
      </Button>
      <Button size="sm">
        <Spinner /> Saving
      </Button>
      <Button>
        <Spinner /> Saving
      </Button>
      <Button size="lg">
        <Spinner /> Saving
      </Button>
    </div>
  ),
};

export const Stopped: Story = {
  args: { size: "lg", spinning: false },
};
