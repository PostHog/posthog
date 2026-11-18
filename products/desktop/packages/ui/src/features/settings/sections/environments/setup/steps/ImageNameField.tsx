import { Shuffle } from "@phosphor-icons/react";
import {
  type EnvironmentSetupPlan,
  withImageName,
} from "@posthog/core/settings/environmentSetup";
import { randomImageName } from "@posthog/core/settings/imagePreset";
import { Button, Input, Label, Text } from "@posthog/quill";
import { StepFieldError } from "@posthog/ui/features/settings/sections/environments/setup/StepFieldError";
import { useId } from "react";

interface ImageNameFieldProps {
  plan: EnvironmentSetupPlan;
  onChange: (plan: EnvironmentSetupPlan) => void;
  error: string | null;
  label: string;
  dataAttr: string;
  randomNameDataAttr: string;
}

export function ImageNameField({
  plan,
  onChange,
  error,
  label,
  dataAttr,
  randomNameDataAttr,
}: ImageNameFieldProps) {
  const nameId = useId();
  const errorId = useId();

  return (
    <>
      <Label htmlFor={nameId} className="font-medium text-[12.5px]">
        {label}
      </Label>
      <div className="flex items-center gap-2">
        <Input
          id={nameId}
          className="h-8 flex-1 text-[12.5px]"
          value={plan.imageName}
          placeholder="e.g. Playwright + Node 22"
          data-attr={dataAttr}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) =>
            onChange(withImageName(plan, event.target.value))
          }
        />
        <Button
          variant="outline"
          size="sm"
          data-attr={randomNameDataAttr}
          onClick={() => onChange(withImageName(plan, randomImageName()))}
        >
          <Shuffle size={12} />
          Random name
        </Button>
      </div>
      {error ? (
        <StepFieldError id={errorId}>{error}</StepFieldError>
      ) : (
        <Text className="text-(--gray-10) text-[11.5px]">
          Shown wherever an environment picks its base image.
        </Text>
      )}
    </>
  );
}
