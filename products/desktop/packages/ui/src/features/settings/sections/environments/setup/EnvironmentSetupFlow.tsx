import {
  type EnvironmentSetupPlan,
  emptyEnvironmentSetupPlan,
  planEnvironmentInput,
  type SetupScope,
} from "@posthog/core/settings/environmentSetup";
import { Spinner } from "@posthog/quill";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { useHandleOpenTask } from "@posthog/ui/features/deep-links/useHandleOpenTask";
import {
  EnvironmentSetupForm,
  type ImageBuildMode,
} from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentSetupForm";
import { submitEnvironmentPlan } from "@posthog/ui/features/settings/sections/environments/setup/submitEnvironmentPlan";
import { useImageFromPlan } from "@posthog/ui/features/settings/sections/environments/setup/useImageFromPlan";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";
import { useState } from "react";

interface EnvironmentSetupFlowProps {
  /** "image" creates only an image; "environment" creates or updates one. */
  scope?: SetupScope;
  defaultRepository: string | null;
  /** True when the flow should start with a new image selected. */
  buildImage?: boolean;
  /** Called with the image whose build just started, so a caller can follow it. */
  onDone: (building: SandboxCustomImage | null) => void;
  /** True when a surrounding dialog already supplies the title and the way back. */
  embedded?: boolean;
}

/**
 * Creates the image the plan describes, then the environment that uses it, so
 * the flow always ends with something a session can start on.
 *
 * Waits for the environments and images first: both decide which choices the
 * early steps can offer, and a plan seeded from an empty list offers the wrong
 * ones. The wait also settles whether custom images are available at all,
 * which the plan is seeded with, so the loaded form owns the plan state.
 */
export function EnvironmentSetupFlow({
  scope = "environment",
  defaultRepository,
  buildImage = false,
  onDone,
  embedded = false,
}: EnvironmentSetupFlowProps) {
  const {
    images,
    isLoading: imagesLoading,
    customImagesEnabled,
    customImagesDisabled,
  } = useSandboxCustomImages();
  const { environments, isLoading: environmentsLoading } =
    useSandboxEnvironments();

  if (imagesLoading || environmentsLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <LoadedSetupFlow
      scope={scope}
      defaultRepository={defaultRepository}
      buildImage={buildImage}
      customImages={customImagesEnabled && !customImagesDisabled}
      images={images}
      environments={environments}
      onDone={onDone}
      embedded={embedded}
    />
  );
}

interface LoadedSetupFlowProps {
  scope: SetupScope;
  defaultRepository: string | null;
  buildImage: boolean;
  customImages: boolean;
  images: readonly SandboxCustomImage[];
  environments: readonly { id: string; name: string }[];
  onDone: (building: SandboxCustomImage | null) => void;
  embedded: boolean;
}

function LoadedSetupFlow({
  scope,
  defaultRepository,
  buildImage,
  customImages,
  images,
  environments,
  onDone,
  embedded,
}: LoadedSetupFlowProps) {
  const image = useImageFromPlan();
  const {
    createMutation: createEnvironment,
    updateMutation: updateEnvironment,
  } = useSandboxEnvironments();
  const handleOpenTask = useHandleOpenTask();
  const [plan, setPlan] = useState<EnvironmentSetupPlan>(() =>
    emptyEnvironmentSetupPlan({
      repository: defaultRepository,
      buildImage,
      scope,
      customImages,
    }),
  );

  const submit = async (mode: ImageBuildMode | null) => {
    const result = await submitEnvironmentPlan(plan, mode === "build", {
      image,
      applyEnvironment: async (customImageId) => {
        if (plan.scope !== "environment") return;
        if (plan.target === "existing" && plan.environmentId !== null) {
          // Attaching an image is all this branch changes, so with custom
          // images unavailable there is nothing to write.
          if (!plan.customImages) return;
          await updateEnvironment.mutateAsync({
            id: plan.environmentId,
            custom_image_id: customImageId,
          });
          return;
        }
        await createEnvironment.mutateAsync(
          planEnvironmentInput(plan, customImageId),
        );
      },
    });
    if (result === null) return;

    if (result.created !== null && mode === "build") {
      onDone(result.created);
      return;
    }
    onDone(null);
    if (result.created?.builder_task_id) {
      void handleOpenTask(result.created.builder_task_id);
    }
  };

  return (
    <EnvironmentSetupForm
      plan={plan}
      onChange={setPlan}
      environments={environments.map((environment) => ({
        id: environment.id,
        name: environment.name,
      }))}
      images={images}
      saving={
        image.pending ||
        createEnvironment.isPending ||
        updateEnvironment.isPending
      }
      embedded={embedded}
      onCancel={() => onDone(null)}
      onSubmit={(mode) => void submit(mode)}
    />
  );
}
