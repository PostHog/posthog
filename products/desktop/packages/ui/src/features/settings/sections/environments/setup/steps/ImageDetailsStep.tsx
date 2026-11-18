import {
  type EnvironmentSetupPlan,
  withRepositories,
} from "@posthog/core/settings/environmentSetup";
import { Checkbox, Label, Text } from "@posthog/quill";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { StepBody } from "@posthog/ui/features/settings/sections/environments/setup/StepBody";
import { ImageNameField } from "@posthog/ui/features/settings/sections/environments/setup/steps/ImageNameField";
import { useId } from "react";

interface ImageDetailsStepProps {
  plan: EnvironmentSetupPlan;
  onChange: (plan: EnvironmentSetupPlan) => void;
  error: string | null;
}

/**
 * The image on its own: what it is called and which repository it is built for.
 * No environment is created here. An image is reused by any environment that
 * picks it as its base.
 */
export function ImageDetailsStep({
  plan,
  onChange,
  error,
}: ImageDetailsStepProps) {
  const privateId = useId();

  return (
    <StepBody
      title="What is this image for?"
      description="A sandbox image with your tools already installed; any environment can start from it"
    >
      <div className="flex max-w-[520px] flex-col gap-2">
        <ImageNameField
          plan={plan}
          onChange={onChange}
          error={error}
          label="Name"
          dataAttr="image-setup-name"
          randomNameDataAttr="image-setup-random-name"
        />
      </div>

      <div className="flex flex-col gap-2 border-(--gray-4) border-t border-dashed pt-4">
        <Label className="font-medium text-[12.5px]">Repository</Label>
        <RepositoriesField
          max={1}
          maxReason="An image is built for one repository"
          selected={[...plan.repositories]}
          integrationId={null}
          onChange={(repositories) =>
            onChange(withRepositories(plan, repositories))
          }
        />
        <Text className="max-w-[56ch] text-(--gray-10) text-[11.5px] leading-snug">
          The builder clones it to check its dependencies come up, and setup
          commands run in a checkout of it. One repository, and leaving it empty
          builds a tools-only image.
        </Text>
      </div>

      <label
        htmlFor={privateId}
        className="flex w-fit cursor-pointer items-center gap-2"
      >
        <Checkbox
          id={privateId}
          checked={plan.private}
          data-attr="image-setup-private"
          onCheckedChange={(checked) =>
            onChange({ ...plan, private: checked === true })
          }
        />
        <Text className="text-(--gray-11) text-[12px]">Only visible to me</Text>
      </label>
    </StepBody>
  );
}
