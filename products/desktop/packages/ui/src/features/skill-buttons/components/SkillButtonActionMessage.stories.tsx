import { SkillButtonActionMessage } from "@posthog/ui/features/skill-buttons/components/SkillButtonActionMessage";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof SkillButtonActionMessage> = {
  title: "Skill Buttons/SkillButtonActionMessage",
  component: SkillButtonActionMessage,
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof SkillButtonActionMessage>;

export const AddAnalytics: Story = {
  args: {
    buttonId: "add-analytics",
  },
};

export const CreateFeatureFlag: Story = {
  args: {
    buttonId: "create-feature-flags",
  },
};

export const RunExperiment: Story = {
  args: {
    buttonId: "run-experiment",
  },
};

export const AddErrorTracking: Story = {
  args: {
    buttonId: "add-error-tracking",
  },
};

export const InstrumentLlmCalls: Story = {
  args: {
    buttonId: "instrument-llm-calls",
  },
};

export const AddLogging: Story = {
  args: {
    buttonId: "add-logging",
  },
};
