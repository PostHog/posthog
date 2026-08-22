import { EMPTY_SPEND_LIMITS } from "@posthog/core/billing/spendLimits";
import { SpendLimitRow } from "@posthog/ui/features/settings/sections/SpendLimitRow";
import type { Meta, StoryObj } from "@storybook/react";

const meta: Meta<typeof SpendLimitRow> = {
  title: "Cost management/SpendLimitRow",
  component: SpendLimitRow,
  args: { onCommit: () => {} },
  decorators: [
    (Story) => (
      <div className="max-w-3xl p-8">
        <div className="rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) px-4 py-3.5">
          <Story />
        </div>
      </div>
    ),
  ],
};

export default meta;

export const PerDayUnderBothLines: StoryObj<typeof SpendLimitRow> = {
  args: {
    scope: "day",
    title: "Per day",
    spentUsd: 7.31,
    markerUsd: 12.4,
    markerLabel: "avg $12.40",
    limits: { ...EMPTY_SPEND_LIMITS, dailyWarnUsd: 20, dailyStopUsd: 50 },
  },
};

export const PerDayPastWarning: StoryObj<typeof SpendLimitRow> = {
  args: {
    scope: "day",
    title: "Per day",
    spentUsd: 31.5,
    markerUsd: 12.4,
    limits: { ...EMPTY_SPEND_LIMITS, dailyWarnUsd: 20, dailyStopUsd: 50 },
  },
};

export const PerDayStopped: StoryObj<typeof SpendLimitRow> = {
  args: {
    scope: "day",
    title: "Per day",
    spentUsd: 52.8,
    markerUsd: 12.4,
    limits: { ...EMPTY_SPEND_LIMITS, dailyWarnUsd: 20, dailyStopUsd: 50 },
  },
};

export const NoLinesSet: StoryObj<typeof SpendLimitRow> = {
  args: {
    scope: "month",
    title: "Per month",
    spentUsd: 84.2,
    limits: EMPTY_SPEND_LIMITS,
  },
};
