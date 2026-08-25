import {
  type EnvironmentSetupPlan,
  isPlanDirty,
  planEnvironmentInput,
  planFromEnvironment,
} from "@posthog/core/settings/environmentSetup";
import { Spinner } from "@posthog/quill";
import type {
  SandboxCustomImage,
  SandboxEnvironment,
} from "@posthog/shared/domain-types";
import { EnvironmentEditForm } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentEditForm";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";
import { useState } from "react";

interface EnvironmentEditPageProps {
  environment: SandboxEnvironment;
  onDone: () => void;
  /** Leaves for the image flow, which is where images get built. */
  onBuildNewImage: () => void;
}

/**
 * Saves an edited environment. Building an image happens in the image flow,
 * so this page only ever points the environment at one that exists.
 *
 * Waits for the images first: whether custom images are available seeds the
 * plan, so seeding before the answer arrives would let a late billing error
 * reshape the saved baseline and mark an untouched form dirty.
 */
export function EnvironmentEditPage({
  environment,
  onDone,
  onBuildNewImage,
}: EnvironmentEditPageProps) {
  const { images, isLoading, customImagesEnabled, customImagesDisabled } =
    useSandboxCustomImages();

  if (isLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <LoadedEditPage
      environment={environment}
      images={images}
      customImages={customImagesEnabled && !customImagesDisabled}
      onDone={onDone}
      onBuildNewImage={onBuildNewImage}
    />
  );
}

interface LoadedEditPageProps extends EnvironmentEditPageProps {
  images: readonly SandboxCustomImage[];
  customImages: boolean;
}

function LoadedEditPage({
  environment,
  images,
  customImages,
  onDone,
  onBuildNewImage,
}: LoadedEditPageProps) {
  const { updateMutation, deleteMutation } = useSandboxEnvironments();
  const [saved] = useState<EnvironmentSetupPlan>(() =>
    planFromEnvironment(environment, { customImages }),
  );
  const [plan, setPlan] = useState<EnvironmentSetupPlan>(saved);
  const dirty = isPlanDirty(plan, saved);

  const save = async () => {
    try {
      const customImageId =
        plan.baseImage === "existing" ? plan.existingImageId : null;
      await updateMutation.mutateAsync({
        id: environment.id,
        ...planEnvironmentInput(plan, customImageId),
      });
      onDone();
    } catch {
      // The mutation's onError toast already explains the failure.
    }
  };

  const archive = async () => {
    try {
      await deleteMutation.mutateAsync(environment.id);
      onDone();
    } catch {
      // The mutation's onError toast already explains the failure.
    }
  };

  return (
    <EnvironmentEditForm
      plan={plan}
      onChange={setPlan}
      images={images}
      environmentName={environment.name}
      variablesAlreadySet={environment.has_environment_variables}
      saving={updateMutation.isPending}
      deleting={deleteMutation.isPending}
      onCancel={onDone}
      onSave={() => void save()}
      onArchive={() => void archive()}
      onBuildNewImage={onBuildNewImage}
      dirty={dirty}
    />
  );
}
