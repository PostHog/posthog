import {
  type BaseImageChoice,
  type EnvironmentSetupPlan,
  withImageName,
} from "@posthog/core/settings/environmentSetup";
import { Button, Input, Label, Text } from "@posthog/quill";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { StepBody } from "@posthog/ui/features/settings/sections/environments/setup/StepBody";
import { RadioCards } from "@posthog/ui/primitives/RadioCards";
import { useId } from "react";

interface BaseImageStepProps {
  plan: EnvironmentSetupPlan;
  images: readonly SandboxCustomImage[];
  onChange: (plan: EnvironmentSetupPlan) => void;
  /**
   * Building an image inline only makes sense while setting an environment up.
   * When editing one, it leaves for the image flow instead of hiding a second
   * kind of creation inside a form about something else.
   */
  onBuildNewImage?: () => void;
  /** Why leaving now is not offered, e.g. unsaved changes. */
  buildNewDisabledReason?: string | null;
}

/** Where sessions start from: the standard image, one you have, or a new one. */
export function BaseImageStep({
  plan,
  images,
  onChange,
  onBuildNewImage,
  buildNewDisabledReason,
}: BaseImageStepProps) {
  const nameId = useId();
  const ready = images.filter((image) => image.status === "ready");
  const linksOut = onBuildNewImage !== undefined;

  return (
    <StepBody
      title="Base image"
      description="What every session in this environment boots from."
    >
      <RadioCards<BaseImageChoice>
        ariaLabel="Base image"
        dataAttrPrefix="environment-setup-image"
        value={plan.baseImage}
        onChange={(baseImage) => onChange({ ...plan, baseImage })}
        options={[
          {
            value: "default",
            title: "Standard image",
            description: "Sessions install what they need each run.",
          },
          ...(linksOut
            ? []
            : [
                {
                  value: "new" as const,
                  title: "Build a new image",
                  description: "Pick its tools and setup commands next.",
                },
              ]),
          {
            value: "existing",
            title: "An image I have",
            description:
              ready.length === 0
                ? "None have finished building yet."
                : ready.length === 1
                  ? "Start from the one you have ready."
                  : `Start from one of your ${ready.length} ready.`,
            disabled: ready.length === 0,
          },
        ]}
      />

      {linksOut && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="link-muted"
            size="sm"
            disabled={buildNewDisabledReason != null}
            data-attr="environment-edit-build-image"
            onClick={onBuildNewImage}
          >
            Build a new image
          </Button>
          <Text className="text-(--gray-10) text-[11.5px]">
            {buildNewDisabledReason ??
              "Opens the image flow. Come back here to pick it once it is ready."}
          </Text>
        </div>
      )}

      {plan.baseImage === "existing" && (
        <div className="flex max-w-[520px] flex-col gap-2 border-(--gray-4) border-t border-dashed pt-4">
          <Label className="font-medium text-[12.5px]">Image</Label>
          <SettingsSelect
            value={plan.existingImageId}
            ariaLabel="Which image"
            placeholder="Pick an image"
            options={ready.map((image) => ({
              value: image.id,
              label: image.repository
                ? `${image.name} · ${image.repository}`
                : image.name,
            }))}
            onChange={(existingImageId) =>
              onChange({ ...plan, existingImageId })
            }
          />
        </div>
      )}

      {plan.baseImage === "new" && (
        <div className="flex max-w-[520px] flex-col gap-2 border-(--gray-4) border-t border-dashed pt-4">
          <Label htmlFor={nameId} className="font-medium text-[12.5px]">
            Image name
          </Label>
          <Input
            id={nameId}
            className="h-8 text-[12.5px]"
            value={plan.imageName}
            placeholder="e.g. Playwright + Node 22"
            data-attr="environment-setup-image-name"
            onChange={(event) =>
              onChange(withImageName(plan, event.target.value))
            }
          />
          <Text className="text-(--gray-10) text-[11.5px]">
            Shown wherever an environment picks its base image.
          </Text>
        </div>
      )}
    </StepBody>
  );
}
