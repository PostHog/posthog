import { TimezoneTimestamp } from "@posthog/ui/primitives/TimezoneTimestamp";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof TimezoneTimestamp> = {
  title: "Components/UI/TimezoneTimestamp",
  component: TimezoneTimestamp,
  parameters: { layout: "centered" },
  args: {
    timestamp: new Date("2026-07-23T01:00:00.000Z"),
    timezone: "America/Toronto",
  },
};

export default meta;
type Story = StoryObj<typeof TimezoneTimestamp>;

export const Default: Story = {};
