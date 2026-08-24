import {
  buildsImage,
  type EnvironmentSetupPlan,
  planSetupCommands,
  planSpecInput,
  planTools,
  primaryRepository,
} from "@posthog/core/settings/environmentSetup";
import { imagePresetBrief } from "@posthog/core/settings/imagePreset";
import {
  buildImageSpec,
  imageSpecToYaml,
} from "@posthog/core/settings/imageSpec";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";

export interface ImageFromPlan {
  /** Creates the image the plan describes, or null when it builds none. */
  create: (plan: EnvironmentSetupPlan) => Promise<SandboxCustomImage | null>;
  /** Writes the spec and starts the build. */
  build: (plan: EnvironmentSetupPlan, imageId: string) => Promise<void>;
  pending: boolean;
}

/**
 * Turning a plan into an image, shared by setting an environment up and
 * editing one: both can build an image, and both must do it the same way.
 */
export function useImageFromPlan(): ImageFromPlan {
  const { createMutation, buildMutation } = useSandboxCustomImages();

  return {
    create: async (plan) => {
      if (!buildsImage(plan)) return null;
      const repository = primaryRepository(plan);
      const image = await createMutation.mutateAsync({
        name: plan.imageName.trim(),
        description: imagePresetBrief(
          repository,
          planTools(plan),
          planSetupCommands(plan),
        ),
        ...(repository ? { repository } : {}),
        ...(plan.private ? { private: true } : {}),
      });
      return image;
    },
    build: async (plan, imageId) => {
      await buildMutation.mutateAsync({
        id: imageId,
        specYaml: imageSpecToYaml(buildImageSpec(planSpecInput(plan))),
      });
    },
    pending: createMutation.isPending || buildMutation.isPending,
  };
}
