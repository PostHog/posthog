import {
  type EnvironmentSetupPlan,
  type SetupTarget,
  stepError,
  withEnvironmentName,
  withRepositories,
} from "@posthog/core/settings/environmentSetup";
import { Checkbox, Input, Label, Text } from "@posthog/quill";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { StepBody } from "@posthog/ui/features/settings/sections/environments/setup/StepBody";
import { RadioCards } from "@posthog/ui/primitives/RadioCards";
import { useId } from "react";

export interface SetupEnvironmentOption {
  id: string;
  name: string;
}

interface EnvironmentStepProps {
  plan: EnvironmentSetupPlan;
  environments: readonly SetupEnvironmentOption[];
  onChange: (plan: EnvironmentSetupPlan) => void;
  /**
   * Editing one environment: the target is already decided, so the choice
   * between a new one and an existing one has no place on the page.
   */
  editing?: boolean;
}

/**
 * What the environment is for: the repositories its sessions work on, and the
 * name it shows up under. An existing environment can be the target instead,
 * which is how an image reaches one that is already set up.
 */
export function EnvironmentStep({
  plan,
  environments,
  onChange,
  editing = false,
}: EnvironmentStepProps) {
  const nameId = useId();
  const privateId = useId();
  const nameError = stepError(plan, "environment");

  return (
    <StepBody
      title={editing ? "Name and repositories" : "What are you setting up?"}
      description="Name it, and pick the repositories its sessions work on"
    >
      {/* Targeting an existing environment only attaches an image to it, so
          without custom images there is nothing this choice could do. */}
      {!editing && plan.customImages && environments.length > 0 && (
        <RadioCards<SetupTarget>
          ariaLabel="What to set up"
          dataAttrPrefix="environment-setup-target"
          value={plan.target}
          onChange={(target) => onChange({ ...plan, target })}
          options={[
            {
              value: "new",
              title: "A new environment",
              description: "Set up where its sessions run and what they reach.",
            },
            {
              value: "existing",
              title: "An environment I have",
              description: "Give one of them a different base image.",
            },
          ]}
        />
      )}

      {(editing || plan.target === "new") && (
        <div className="flex flex-col gap-2">
          <Label htmlFor={nameId} className="font-medium text-[12.5px]">
            Name
          </Label>
          <Input
            id={nameId}
            className="h-8 max-w-[420px] text-[12.5px]"
            value={plan.environmentName}
            placeholder="e.g. Internal APIs"
            data-attr="environment-setup-name"
            onChange={(event) =>
              onChange(withEnvironmentName(plan, event.target.value))
            }
          />
          <Text className="text-(--gray-10) text-[11.5px]">
            {nameError ?? "Shown in the workspace picker."}
          </Text>
        </div>
      )}

      {!editing && plan.target === "existing" && (
        <div className="flex max-w-[420px] flex-col gap-2">
          <Label className="font-medium text-[12.5px]">Which environment</Label>
          <SettingsSelect
            value={plan.environmentId}
            ariaLabel="Which environment"
            placeholder="Pick an environment"
            options={environments.map((environment) => ({
              value: environment.id,
              label: environment.name,
            }))}
            onChange={(environmentId) => onChange({ ...plan, environmentId })}
          />
          <Text className="text-(--gray-10) text-[11.5px]">
            It keeps its own access settings. Only its base image changes.
          </Text>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <Label className="font-medium text-[12.5px]">Repositories</Label>
        <RepositoriesField
          selected={[...plan.repositories]}
          integrationId={null}
          onChange={(repositories) =>
            onChange(withRepositories(plan, repositories))
          }
        />
        <Text className="max-w-[56ch] text-(--gray-10) text-[11.5px] leading-snug">
          Sessions here work on these. The image is built for the first one, and
          leaving this empty is fine.
        </Text>
      </div>

      {(editing || plan.target === "new") && (
        <label
          htmlFor={privateId}
          className="flex w-fit cursor-pointer items-center gap-2"
        >
          <Checkbox
            id={privateId}
            checked={plan.private}
            data-attr="environment-setup-private"
            onCheckedChange={(checked) =>
              onChange({ ...plan, private: checked === true })
            }
          />
          <Text className="text-(--gray-11) text-[12px]">
            Only visible to me
          </Text>
        </label>
      )}
    </StepBody>
  );
}
