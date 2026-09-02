import { TimezoneConversionTooltip } from "@posthog/ui/primitives/TimezoneConversionTooltip";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof TimezoneConversionTooltip> = {
  title: "Components/UI/TimezoneConversionTooltip",
  component: TimezoneConversionTooltip,
  parameters: { layout: "centered" },
  args: {
    timestamp: new Date("2026-07-23T01:00:00.000Z"),
    timezone: "UTC",
    timezoneLabel: "Schedule",
    open: true,
    children: (
      <span className="cursor-help underline decoration-dotted underline-offset-2">
        Wed, Jul 22, 9:00 PM
      </span>
    ),
  },
};

export default meta;
type Story = StoryObj<typeof TimezoneConversionTooltip>;

export const Light: Story = {
  globals: { theme: "light" },
};

export const Dark: Story = {
  globals: { theme: "dark" },
};
