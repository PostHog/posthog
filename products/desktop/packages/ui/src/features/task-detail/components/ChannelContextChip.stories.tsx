import type { Meta, StoryObj } from "@storybook/react-vite";
import { ChannelContextChip } from "./ChannelContextChip";

const meta = {
  title: "Task Detail/ChannelContextChip",
  component: ChannelContextChip,
  parameters: { layout: "centered" },
} satisfies Meta<typeof ChannelContextChip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ContextLayerConnected: Story = {
  args: { source: "context-layer" },
};
