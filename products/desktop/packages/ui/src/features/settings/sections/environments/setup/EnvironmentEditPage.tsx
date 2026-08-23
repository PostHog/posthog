import {
  type EnvironmentSetupPlan,
  planEnvironmentInput,
  planFromEnvironment,
} from "@posthog/core/settings/environmentSetup";
import type { SandboxEnvironment } from "@posthog/shared/domain-types";
import { EnvironmentEditForm } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentEditForm";
import { useImageFromPlan } from "@posthog/ui/features/settings/sections/environments/setup/useImageFromPlan";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";
import { toast } from "@posthog/ui/primitives/toast";
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
  const saved = planFromEnvironment(environment);
  const [plan, setPlan] = useState<EnvironmentSetupPlan>(saved);
  const dirty = JSON.stringify(plan) !== JSON.stringify(saved);

  const save = async () => {
    const created = await image.create(plan);
    const payload = planEnvironmentInput(
      plan,
      created?.id ??
        (plan.baseImage === "existing" ? plan.existingImageId : null),
    );
    if (customImagesDisabled) delete payload.custom_image_id;
    await updateMutation.mutateAsync({ id: environment.id, ...payload });

    if (created !== null) {
      await image.build(plan, created.id);
      toast.success("Building your image", {
        description: "It scans first, then builds. This takes a few minutes.",
      });
    }
    onDone();
  };

  const archive = async () => {
    await deleteMutation.mutateAsync(environment.id);
    onDone();
  };

  return (
    <EnvironmentEditForm
      plan={plan}
      onChange={setPlan}
      host="github"
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
