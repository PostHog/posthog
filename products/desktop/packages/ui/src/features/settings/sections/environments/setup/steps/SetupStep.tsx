import { Plus } from "@phosphor-icons/react";
import {
  type EnvironmentSetupPlan,
  primaryRepository,
  type SetupLine,
} from "@posthog/core/settings/environmentSetup";
import {
  SETUP_COMMAND_GROUPS,
  SETUP_COMMAND_SUGGESTIONS,
} from "@posthog/core/settings/imagePreset";
import {
  Button,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { StepBody } from "@posthog/ui/features/settings/sections/environments/setup/StepBody";
import { SetupCommandList } from "@posthog/ui/features/settings/sections/environments/setup/steps/SetupCommandList";
import {
  type RadioCardOption,
  RadioCards,
} from "@posthog/ui/primitives/RadioCards";
import { useState } from "react";

interface SetupStepProps {
  plan: EnvironmentSetupPlan;
  onChange: (plan: EnvironmentSetupPlan) => void;
  /** Sends the user back to pick a repository, which setup commands need. */
  onPickRepository: () => void;
}

/** Whether the builder session decides what to install, or the plan says. */
type SetupMode = "auto" | "custom";

/**
 * Commands that run while the image builds. They need a repository to run
 * inside, so without one the step points back rather than showing dead inputs.
 */
export function SetupStep({
  plan,
  onChange,
  onPickRepository,
}: SetupStepProps) {
  const repository = primaryRepository(plan);
  const [mode, setMode] = useState<SetupMode>(
    plan.setupLines.length > 0 ? "custom" : "auto",
  );

  if (repository === null) {
    return (
      <StepBody
        title="Setup commands"
        description="Setup commands run inside a repository checkout, so this image has nothing to run them in."
      >
        <Button
          variant="outline"
          size="sm"
          onClick={onPickRepository}
          data-attr="environment-setup-pick-repository"
        >
          Pick a repository
        </Button>
      </StepBody>
    );
  }

  const options: readonly RadioCardOption<SetupMode>[] = [
    {
      value: "auto",
      title: "Auto",
      description: `A builder session clones ${repository} and installs the runtimes and package managers it pins.`,
    },
    {
      value: "custom",
      title: "Custom",
      description:
        "You give the commands. They run in a checkout while the image builds.",
    },
  ];

  return (
    <StepBody
      title="Setup commands"
      description={`What runs in a checkout of ${repository} while the image builds, so a session starts with dependencies already warm.`}
    >
      <RadioCards<SetupMode>
        value={mode}
        options={options}
        ariaLabel="How setup commands are decided"
        dataAttrPrefix="environment-setup-mode"
        onChange={(next) => {
          setMode(next);
          if (next === "auto" && plan.setupLines.length > 0) {
            onChange({ ...plan, setupLines: [] });
          }
        }}
      />

      {mode === "custom" && (
        <div className="flex flex-col gap-4">
          <SetupCommandList
            lines={plan.setupLines}
            onChange={(setupLines: SetupLine[]) =>
              onChange({ ...plan, setupLines })
            }
          />

          <div className="flex flex-col gap-3 border-(--gray-4) border-t border-dashed pt-4">
            {SETUP_COMMAND_GROUPS.map((group) => {
              const suggestions = SETUP_COMMAND_SUGGESTIONS.filter(
                (suggestion) =>
                  suggestion.group === group.id &&
                  !plan.setupLines.some(
                    (line) => line.value === suggestion.command,
                  ),
              );
              if (suggestions.length === 0) return null;
              return (
                <div key={group.id} className="flex flex-col gap-1.5">
                  <Text className="font-medium text-(--gray-10) text-[10.5px] uppercase tracking-wide">
                    {group.label}
                  </Text>
                  <div className="flex flex-wrap gap-1.5">
                    {suggestions.map((suggestion) => (
                      <Tooltip key={suggestion.id}>
                        <TooltipTrigger
                          render={
                            <Button
                              variant="outline"
                              size="sm"
                              data-attr={`environment-setup-suggest-${suggestion.id}`}
                              onClick={() =>
                                onChange({
                                  ...plan,
                                  setupLines: [
                                    ...plan.setupLines,
                                    {
                                      id: crypto.randomUUID(),
                                      value: suggestion.command,
                                    },
                                  ],
                                })
                              }
                            >
                              <Plus size={11} />
                              {suggestion.label}
                            </Button>
                          }
                        />
                        <TooltipContent className="max-w-[280px]">
                          <span className="font-mono">
                            {suggestion.command}
                          </span>
                          <br />
                          {suggestion.note}
                        </TooltipContent>
                      </Tooltip>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </StepBody>
  );
}
