import {
  type EnvironmentSetupPlan,
  planEnvironmentInput,
  planFromEnvironment,
} from "@posthog/core/settings/environmentSetup";
import type { SandboxEnvironment } from "@posthog/shared/domain-types";
import { EnvironmentEditForm } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentEditForm";
import { submitEnvironmentPlan } from "@posthog/ui/features/settings/sections/environments/setup/submitEnvironmentPlan";
import { useImageFromPlan } from "@posthog/ui/features/settings/sections/environments/setup/useImageFromPlan";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";
import { useState } from "react";

interface EnvironmentEditPageProps {
  environment: SandboxEnvironment;
  onDone: () => void;
  /** Leaves for the image flow, which is where images get built. */
  onBuildNewImage: () => void;
}

/** Saves an edited environment, building a new base image first when one was asked for. */
export function EnvironmentEditPage({
  environment,
  onDone,
  onBuildNewImage,
}: EnvironmentEditPageProps) {
  const { updateMutation, deleteMutation } = useSandboxEnvironments();
  const { images, customImagesDisabled } = useSandboxCustomImages();
  const image = useImageFromPlan();
  const saved = planFromEnvironment(environment, {
    customImages: !customImagesDisabled,
  });
  const [plan, setPlan] = useState<EnvironmentSetupPlan>(saved);
  const dirty = JSON.stringify(plan) !== JSON.stringify(saved);

  const save = async () => {
    const result = await submitEnvironmentPlan(plan, true, {
      image,
      applyEnvironment: async (customImageId) => {
        await updateMutation.mutateAsync({
          id: environment.id,
          ...planEnvironmentInput(plan, customImageId),
        });
      },
    });
    if (result !== null) onDone();
  };

  const archive = async () => {
    await deleteMutation.mutateAsync(environment.id);
    onDone();
  };

  return (
    <EnvironmentEditForm
      plan={plan}
      onChange={setPlan}
      images={images}
      environmentName={environment.name}
      variablesAlreadySet={environment.has_environment_variables}
      saving={image.pending || updateMutation.isPending}
      deleting={deleteMutation.isPending}
      onCancel={onDone}
      onSave={() => void save()}
      onArchive={() => void archive()}
      onBuildNewImage={onBuildNewImage}
      dirty={dirty}
    />
  );
}
