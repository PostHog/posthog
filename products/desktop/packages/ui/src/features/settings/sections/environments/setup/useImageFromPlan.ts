import {
  buildsImage,
  type EnvironmentSetupPlan,
  planImageInput,
  planSpecInput,
} from "@posthog/core/settings/environmentSetup";
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

/** Turning a plan into an image, for the setup flow. */
export function useImageFromPlan(): ImageFromPlan {
  const { createMutation, buildMutation } = useSandboxCustomImages();

  return {
    create: async (plan) => {
      if (!buildsImage(plan)) return null;
      return await createMutation.mutateAsync(planImageInput(plan));
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
