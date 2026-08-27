import { LoadingLogo } from "@posthog/ui/primitives/LoadingLogo";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Primitives/LoadingLogo",
  component: LoadingLogo,
  parameters: { layout: "centered" },
} satisfies Meta<typeof LoadingLogo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { size: 96 },
};

export const Large: Story = {
  args: { size: 240 },
};
