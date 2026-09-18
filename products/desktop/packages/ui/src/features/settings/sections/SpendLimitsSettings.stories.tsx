import {
  EMPTY_SPEND_LIMITS,
  type SpendLimits,
} from "@posthog/core/billing/spendLimits";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SpendLimitsSettingsView } from "./SpendLimitsSettings";

const LINES: SpendLimits = {
  day: { warnUsd: 20, stopUsd: 50 },
  month: { warnUsd: 500, stopUsd: 1000 },
};

const meta: Meta<typeof SpendLimitsSettingsView> = {
  title: "Settings/SpendLimitsSettings",
  component: SpendLimitsSettingsView,
  decorators: [
    (Story) => (
      <div className="mx-auto max-w-3xl p-6">
        <Story />
      </div>
    ),
  ],
  args: {
    spendLimits: LINES,
    totals: { todayUsd: 7.31, monthUsd: 84.2, avgDailyUsd: 12.4 },
    stopAvailable: true,
    onCommit: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof SpendLimitsSettingsView>;

export const BelowLines: Story = {};

export const AllOff: Story = {
  args: { spendLimits: EMPTY_SPEND_LIMITS },
};

export const NoLinesNoHistory: Story = {
  args: { spendLimits: EMPTY_SPEND_LIMITS, totals: null },
};

export const WarningCrossed: Story = {
  args: { totals: { todayUsd: 26.4, monthUsd: 231.9, avgDailyUsd: 12.4 } },
};

export const StopCrossed: Story = {
  args: { totals: { todayUsd: 61.75, monthUsd: 412.5, avgDailyUsd: 15.8 } },
};

/** No gateway behind the lines, so they inform and pause this app only. */
export const InformOnly: Story = {
  args: { stopAvailable: false },
};
