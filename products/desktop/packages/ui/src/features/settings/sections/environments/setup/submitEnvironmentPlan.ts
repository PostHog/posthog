import type { EnvironmentSetupPlan } from "@posthog/core/settings/environmentSetup";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import type { ImageFromPlan } from "@posthog/ui/features/settings/sections/environments/setup/useImageFromPlan";
import { toast } from "@posthog/ui/primitives/toast";

export interface SubmitEnvironmentPlanDeps {
  image: ImageFromPlan;
  /** Persists the environment side of the plan, pointed at the image to use. */
  applyEnvironment: (customImageId: string | null) => Promise<void>;
}

/**
 * The one order the setup flow saves a plan in: image record first, then the
 * environment that points at it, then the build. A failed step surfaces as a
 * toast and returns null so the caller stays on the form instead of closing
 * over a half-saved result.
 */
export async function submitEnvironmentPlan(
  plan: EnvironmentSetupPlan,
  startBuild: boolean,
  { image, applyEnvironment }: SubmitEnvironmentPlanDeps,
): Promise<{ created: SandboxCustomImage | null } | null> {
  try {
    const created = await image.create(plan);
    const customImageId =
      created?.id ??
      (plan.baseImage === "existing" ? plan.existingImageId : null);
    await applyEnvironment(customImageId);
    if (created !== null && startBuild) {
      await image.build(plan, created.id);
      toast.success("Building your image", {
        description: "It scans first, then builds. This takes a few minutes.",
      });
    }
    return { created };
  } catch (error) {
    toast.error("Couldn't save your changes", {
      description: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}
