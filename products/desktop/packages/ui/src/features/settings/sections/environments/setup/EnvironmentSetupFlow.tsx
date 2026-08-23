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
import { useImageFromPlan } from "@posthog/ui/features/settings/sections/environments/setup/useImageFromPlan";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";
import { toast } from "@posthog/ui/primitives/toast";
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
 * ones.
 */
export function EnvironmentSetupFlow({
  scope = "environment",
  defaultRepository,
  buildImage = false,
  onDone,
  embedded = false,
}: EnvironmentSetupFlowProps) {
  const image = useImageFromPlan();
  const { images, isLoading: imagesLoading } = useSandboxCustomImages();
  const {
    environments,
    isLoading: environmentsLoading,
    createMutation: createEnvironment,
    updateMutation: updateEnvironment,
  } = useSandboxEnvironments();
  const handleOpenTask = useHandleOpenTask();
  const [plan, setPlan] = useState<EnvironmentSetupPlan>(() =>
    emptyEnvironmentSetupPlan({
      repository: defaultRepository,
      buildImage,
      scope,
    }),
  );

  const submit = async (mode: ImageBuildMode | null) => {
    const created = await image.create(plan);
    const customImageId =
      created?.id ??
      (plan.baseImage === "existing" ? plan.existingImageId : null);

    if (plan.scope === "environment") {
      if (plan.target === "existing" && plan.environmentId !== null) {
        await updateEnvironment.mutateAsync({
          id: plan.environmentId,
          custom_image_id: customImageId,
        });
      } else {
        await createEnvironment.mutateAsync(
          planEnvironmentInput(plan, customImageId),
        );
      }
    }

    if (created !== null && mode === "build") {
      await image.build(plan, created.id);
      toast.success("Building your image", {
        description: "It scans first, then builds. This takes a few minutes.",
      });
      onDone(created);
      return;
    }
    onDone(null);
    if (created?.builder_task_id) void handleOpenTask(created.builder_task_id);
  };

  if (imagesLoading || environmentsLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }

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
