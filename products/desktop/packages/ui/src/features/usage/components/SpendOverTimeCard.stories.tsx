import type { SpendAnalysisFilledDay } from "@posthog/core/billing/spendAnalysisTypes";
import { EMPTY_SPEND_LIMITS } from "@posthog/core/billing/spendLimits";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";
import { SpendOverTimeCard } from "./SpendOverTimeCard";

function day(
  dayIso: string,
  costUsd: number,
  models: { model: string; share: number }[] = [
    { model: "claude-opus-4-8", share: 0.7 },
    { model: "claude-haiku-4-5", share: 0.3 },
  ],
): SpendAnalysisFilledDay {
  return {
    day: dayIso,
    cost_usd: costUsd,
    event_count: Math.round(costUsd * 20),
    input_tokens: Math.round(costUsd * 90_000),
    output_tokens: Math.round(costUsd * 12_000),
    models: models.map((entry) => ({
      day: dayIso,
      model: entry.model,
      cost_usd: costUsd * entry.share,
      input_tokens: Math.round(costUsd * entry.share * 90_000),
      output_tokens: Math.round(costUsd * entry.share * 12_000),
      generation_count: Math.round(costUsd * entry.share * 20),
    })),
  };
}

const COSTS = [4, 11, 7, 23, 15, 3, 0, 9, 27, 18, 6, 12, 54, 21] as const;
const FILLED_DAYS = COSTS.map((cost, index) =>
  day(`2026-08-${String(index + 5).padStart(2, "0")}`, cost),
);

function SpendLimitsDecorator({
  children,
  warnUsd,
  stopUsd,
}: {
  children: React.ReactNode;
  warnUsd: number | null;
  stopUsd: number | null;
}) {
  useEffect(() => {
    useSettingsStore.setState({
      spendLimits: { ...EMPTY_SPEND_LIMITS, day: { warnUsd, stopUsd } },
    });
    return () => {
      useSettingsStore.setState({ spendLimits: EMPTY_SPEND_LIMITS });
    };
  }, [warnUsd, stopUsd]);
  return <>{children}</>;
}

const meta: Meta<typeof SpendOverTimeCard> = {
  title: "Usage/SpendOverTimeCard",
  component: SpendOverTimeCard,
  decorators: [
    (Story) => (
      <div className="mx-auto max-w-3xl p-6">
        <Story />
      </div>
    ),
  ],
  args: { filledDays: FILLED_DAYS },
};

export default meta;
type Story = StoryObj<typeof SpendOverTimeCard>;

export const NoLimits: Story = {
  decorators: [
    (Story) => (
      <SpendLimitsDecorator warnUsd={null} stopUsd={null}>
        <Story />
      </SpendLimitsDecorator>
    ),
  ],
};

export const WithSpendLines: Story = {
  decorators: [
    (Story) => (
      <SpendLimitsDecorator warnUsd={20} stopUsd={50}>
        <Story />
      </SpendLimitsDecorator>
    ),
  ],
};
