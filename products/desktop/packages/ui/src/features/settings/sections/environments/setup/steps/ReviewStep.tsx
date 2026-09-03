import {
  buildsImage,
  type EnvironmentSetupPlan,
  filledEnvVars,
  planSpecInput,
  planTools,
  stepError,
} from "@posthog/core/settings/environmentSetup";
import { isDirectlyInstallable } from "@posthog/core/settings/imagePreset";
import {
  buildImageSpec,
  imageSpecToYaml,
} from "@posthog/core/settings/imageSpec";
import { Text } from "@posthog/quill";
import { StepBody } from "@posthog/ui/features/settings/sections/environments/setup/StepBody";

interface ReviewStepProps {
  plan: EnvironmentSetupPlan;
  /** Names the target and the base image, since the plan holds only their ids. */
  targetName: string;
  baseImageName: string;
}

/** What gets created, including the spec as it will be written. */
export function ReviewStep({
  plan,
  targetName,
  baseImageName,
}: ReviewStepProps) {
  const error = stepError(plan, "review");
  const builderOnly = buildsImage(plan)
    ? planTools(plan).filter((tool) => !isDirectlyInstallable(tool))
    : [];

  return (
    <StepBody title="Review" description="This is what gets created">
      <dl className="flex flex-col gap-2 text-[12.5px]">
        {plan.scope === "image" ? (
          <>
            <ReviewRow
              label="Image"
              value={plan.imageName.trim() || "Unnamed"}
            />
            <ReviewRow
              label="Repository"
              value={plan.repositories[0] ?? "None, tools only"}
            />
            <ReviewRow
              label="Visibility"
              value={plan.private ? "Only me" : "Everyone on the team"}
            />
          </>
        ) : (
          <>
            <ReviewRow
              label="Environment"
              value={
                plan.target === "new" ? `${targetName} (new)` : `${targetName}`
              }
            />
            <ReviewRow
              label="Repositories"
              value={
                plan.repositories.length > 0
                  ? plan.repositories.join(", ")
                  : "None, tools only"
              }
            />
            {plan.target === "new" && (
              <>
                <ReviewRow
                  label="Access"
                  value={
                    plan.networkAccessLevel === "custom"
                      ? `Custom, ${plan.allowedDomainsText.split("\n").filter((line) => line.trim() !== "").length} domains`
                      : plan.networkAccessLevel === "trusted"
                        ? "Trusted sources only"
                        : "Full"
                  }
                />
                <ReviewRow
                  label="Variables"
                  value={
                    filledEnvVars(plan).length === 0
                      ? "None"
                      : filledEnvVars(plan)
                          .map((row) => row.key.trim())
                          .join(", ")
                  }
                />
              </>
            )}
            <ReviewRow label="Base image" value={baseImageName} />
          </>
        )}
      </dl>

      {buildsImage(plan) && error === null && (
        <div className="flex max-w-[60ch] flex-col gap-1.5">
          <Text className="font-medium text-(--gray-11) text-[11px] uppercase tracking-wide">
            Image spec
          </Text>
          <pre className="max-h-[176px] overflow-auto rounded-(--radius-3) border border-border bg-(--gray-2) px-3 py-2.5 font-mono text-(--gray-11) text-[11.5px] leading-relaxed">
            {imageSpecToYaml(buildImageSpec(planSpecInput(plan)))}
          </pre>
        </div>
      )}

      {error && <Text className="text-(--amber-11) text-[12px]">{error}</Text>}

      {error === null && buildsImage(plan) && (
        <Text className="max-w-[60ch] text-(--gray-10) text-[11.5px] leading-snug">
          Building now writes this spec and starts the build, with nothing to
          answer. A session instead opens a task where an agent installs each
          tool, checks the repository comes up, and fixes what fails first.
          {builderOnly.length > 0 &&
            ` ${builderOnly.map((tool) => tool.command).join(", ")} need that, so it is the only route to them.`}
        </Text>
      )}
    </StepBody>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <dt className="w-24 shrink-0 text-(--gray-10)">{label}</dt>
      <dd className="min-w-0 text-(--gray-12)">{value}</dd>
    </div>
  );
}
