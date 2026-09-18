import { AnimatedLogo } from "@posthog/ui/primitives/AnimatedLogo";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Primitives/AnimatedLogo",
  component: AnimatedLogo,
  parameters: { layout: "centered" },
} satisfies Meta<typeof AnimatedLogo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const LoadingScreen: Story = {
  args: { size: 72 },
};

export const TitleBarHover: Story = {
  args: { size: 26, animate: "hover" },
};

export const Large: Story = {
  args: { size: 240 },
};
