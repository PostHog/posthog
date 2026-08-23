import { imagePresetBrief } from "@posthog/core/billing/imagePreset";
import {
  buildImageSpec,
  imageSpecToYaml,
} from "@posthog/core/billing/imageSpec";
import {
  buildsImage,
  type EnvironmentSetupPlan,
  emptyEnvironmentSetupPlan,
  planEnvironmentInput,
  planSetupCommands,
  planSpecInput,
  planTools,
  primaryRepository,
  type SetupScope,
} from "@posthog/core/settings/environmentSetup";
import type {
  SandboxCustomImage,
  SandboxEnvironment,
} from "@posthog/shared/domain-types";
import { useHandleOpenTask } from "@posthog/ui/features/deep-links/useHandleOpenTask";
import {
  EnvironmentSetupForm,
  type ImageBuildMode,
} from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentSetupForm";
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
  environments: readonly SandboxEnvironment[];
  images: readonly SandboxCustomImage[];
  /** Called with the image whose build just started, so a caller can follow it. */
  onDone: (building: SandboxCustomImage | null) => void;
  /** True when a surrounding dialog already supplies the title and the way back. */
  embedded?: boolean;
}

/**
 * Creates the image the plan describes, then the environment that uses it, so
 * the flow always ends with something a session can start on.
 */
export function EnvironmentSetupFlow({
  scope = "environment",
  defaultRepository,
  buildImage = false,
  environments,
  images,
  onDone,
  embedded = false,
}: EnvironmentSetupFlowProps) {
  const { createMutation: createImage, buildMutation } =
    useSandboxCustomImages();
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
    }),
  );

  /** The image the environment will point at, creating one when asked to. */
  const resolveImage = async (): Promise<SandboxCustomImage | null> => {
    if (!buildsImage(plan)) return null;
    const repository = primaryRepository(plan);
    const image = await createImage.mutateAsync({
      name: plan.imageName.trim(),
      description: imagePresetBrief(
        repository,
        planTools(plan, "github"),
        planSetupCommands(plan),
      ),
      ...(repository ? { repository } : {}),
      ...(plan.private ? { private: true } : {}),
    });
    return image;
  };

  const submit = async (mode: ImageBuildMode | null) => {
    const image = await resolveImage();
    const customImageId =
      image?.id ??
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

    if (image !== null && mode === "build") {
      await buildMutation.mutateAsync({
        id: image.id,
        specYaml: imageSpecToYaml(
          buildImageSpec(planSpecInput(plan, "github")),
        ),
      });
      toast.success("Building your image", {
        description: "It scans first, then builds. This takes a few minutes.",
      });
      onDone(image);
      return;
    }
    onDone(null);
    if (image?.builder_task_id) void handleOpenTask(image.builder_task_id);
  };

  return (
    <EnvironmentSetupForm
      plan={plan}
      onChange={setPlan}
      host="github"
      environments={environments.map((environment) => ({
        id: environment.id,
        name: environment.name,
      }))}
      images={images}
      saving={
        createImage.isPending ||
        buildMutation.isPending ||
        createEnvironment.isPending ||
        updateEnvironment.isPending
      }
      embedded={embedded}
      onCancel={() => onDone(null)}
      onSubmit={(mode) => void submit(mode)}
    />
  );
}
