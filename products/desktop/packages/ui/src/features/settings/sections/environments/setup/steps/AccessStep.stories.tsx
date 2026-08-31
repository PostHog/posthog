import {
  type EnvironmentSetupPlan,
  emptyEnvironmentSetupPlan,
} from "@posthog/core/settings/environmentSetup";
import { AccessStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/AccessStep";
import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";

/** Stateful wrapper: the step is driven by its plan, so a story has to hold one. */
function AccessStepStory({
  initialPlan,
  savedVariableKeys = [],
}: {
  initialPlan: EnvironmentSetupPlan;
  savedVariableKeys?: string[];
}) {
  const [plan, setPlan] = useState(initialPlan);
  return (
    <div className="mx-auto max-w-[800px] p-6">
      <AccessStep
        plan={plan}
        onChange={setPlan}
        savedVariableKeys={savedVariableKeys}
      />
    </div>
  );
}

const meta: Meta<typeof AccessStepStory> = {
  title: "Environments/AccessStep",
  component: AccessStepStory,
  args: {
    initialPlan: emptyEnvironmentSetupPlan({ repository: "posthog/posthog" }),
  },
};

export default meta;

export const NoVariablesYet: StoryObj<typeof AccessStepStory> = {};

/** An environment that already holds variables, which is what editing one shows. */
export const VariablesAlreadySaved: StoryObj<typeof AccessStepStory> = {
  args: {
    savedVariableKeys: ["ANTHROPIC_API_KEY", "DATABASE_URL", "OPENAI_API_KEY"],
  },
};

/** Replacing a saved set, which the rows warn about before it happens. */
export const ReplacingSavedVariables: StoryObj<typeof AccessStepStory> = {
  args: {
    initialPlan: {
      ...emptyEnvironmentSetupPlan({ repository: "posthog/posthog" }),
      envVars: [{ id: "a", key: "OPENAI_API_KEY", value: "sk-test" }],
    },
    savedVariableKeys: ["ANTHROPIC_API_KEY", "DATABASE_URL", "OPENAI_API_KEY"],
  },
};
