import {
  type EnvironmentSetupPlan,
  emptyEnvironmentSetupPlan,
} from "@posthog/core/settings/environmentSetup";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { EnvironmentSetupForm } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentSetupForm";
import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";

const image = (overrides: Partial<SandboxCustomImage> = {}) =>
  ({
    id: "image-1",
    name: "posthog toolchain",
    status: "ready",
    version: 3,
    repository: "posthog/posthog",
    private: false,
    ...overrides,
  }) as SandboxCustomImage;

/** Stateful wrapper: the form is driven by its plan, so a story has to hold one. */
function EnvironmentSetupFormStory({
  initialPlan,
  environments,
  images,
  saving = false,
}: {
  initialPlan: EnvironmentSetupPlan;
  environments: { id: string; name: string }[];
  images: SandboxCustomImage[];
  saving?: boolean;
}) {
  const [plan, setPlan] = useState(initialPlan);
  return (
    <div className="mx-auto max-w-[800px] p-6">
      <EnvironmentSetupForm
        plan={plan}
        onChange={setPlan}
        environments={environments}
        images={images}
        saving={saving}
        onCancel={() => {}}
        onSubmit={() => {}}
      />
    </div>
  );
}

const meta: Meta<typeof EnvironmentSetupFormStory> = {
  title: "Environments/EnvironmentSetupForm",
  component: EnvironmentSetupFormStory,
  args: {
    initialPlan: emptyEnvironmentSetupPlan({ repository: "posthog/posthog" }),
    environments: [],
    images: [],
  },
};

export default meta;

export const FirstEnvironment: StoryObj<typeof EnvironmentSetupFormStory> = {};

export const BuildingAnImage: StoryObj<typeof EnvironmentSetupFormStory> = {
  args: {
    initialPlan: {
      ...emptyEnvironmentSetupPlan({ repository: "posthog/posthog" }),
      baseImage: "new",
    },
    environments: [
      { id: "env-1", name: "Internal APIs" },
      { id: "env-2", name: "Read-only" },
    ],
    images: [image()],
  },
};

export const CustomAllowlist: StoryObj<typeof EnvironmentSetupFormStory> = {
  args: {
    initialPlan: {
      ...emptyEnvironmentSetupPlan({ repository: "posthog/posthog" }),
      networkAccessLevel: "custom",
      allowedDomainsText: "github.com\n*.example.com",
      envVars: [
        { id: "a", key: "OPENAI_API_KEY", value: "sk-test" },
        { id: "b", key: "SENTRY_DSN", value: "https://example.com/1" },
      ],
    },
    images: [image()],
  },
};

export const ImageOnly: StoryObj<typeof EnvironmentSetupFormStory> = {
  args: {
    initialPlan: emptyEnvironmentSetupPlan({
      repository: "posthog/posthog",
      scope: "image",
    }),
  },
};
