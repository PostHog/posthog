import { PreviewCard } from "@base-ui/react/preview-card";
import { ArrowLeft } from "@phosphor-icons/react";
import {
  buildsImage,
  type EnvironmentSetupPlan,
  planTools,
  setupSteps,
  setupStepsComplete,
  stepError,
} from "@posthog/core/settings/environmentSetup";
import { isDirectlyInstallable } from "@posthog/core/settings/imagePreset";
import { Button, Card, Text } from "@posthog/quill";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { AccessStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/AccessStep";
import { BaseImageStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/BaseImageStep";
import {
  EnvironmentStep,
  type SetupEnvironmentOption,
} from "@posthog/ui/features/settings/sections/environments/setup/steps/EnvironmentStep";
import { ImageDetailsStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/ImageDetailsStep";
import { ReviewStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/ReviewStep";
import { SetupStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/SetupStep";
import { ToolsStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/ToolsStep";
import { Stepper } from "@posthog/ui/primitives/Stepper";
import { type ReactElement, useState } from "react";

/** Write the spec and build it, or hand the plan to a builder session. */
export type ImageBuildMode = "build" | "builder";

interface EnvironmentSetupFormProps {
  plan: EnvironmentSetupPlan;
  onChange: (plan: EnvironmentSetupPlan) => void;
  environments: readonly SetupEnvironmentOption[];
  images: readonly SandboxCustomImage[];
  saving: boolean;
  onCancel: () => void;
  /** The build mode is null when no image is being built. */
  onSubmit: (mode: ImageBuildMode | null) => void;
  /** True when a surrounding dialog already supplies the title and the way back. */
  embedded?: boolean;
}

/**
 * Sets up a cloud environment in steps: what it is for, what it may reach,
 * what its sessions start from, and a review of all of it. Nothing is created
 * until the last step resolves.
 */
export function EnvironmentSetupForm({
  plan,
  onChange,
  environments,
  images,
  saving,
  onCancel,
  onSubmit,
  embedded = false,
}: EnvironmentSetupFormProps) {
  const [step, setStep] = useState(0);
  const steps = setupSteps(plan);
  const complete = setupStepsComplete(plan);
  const current = Math.min(step, steps.length - 1);
  const currentKey = steps[current].key;
  const isLastStep = current === steps.length - 1;
  const building = buildsImage(plan);
  const needsBuilder =
    building && planTools(plan).some((tool) => !isDirectlyInstallable(tool));
  const canSubmit = !saving && stepError(plan, "review") === null;

  const targetName =
    plan.target === "new"
      ? plan.environmentName.trim() || "Unnamed"
      : (environments.find(
          (environment) => environment.id === plan.environmentId,
        )?.name ?? "Unnamed");
  const baseImageName = building
    ? `${plan.imageName.trim() || "Unnamed"} (building)`
    : plan.baseImage === "existing"
      ? (images.find((image) => image.id === plan.existingImageId)?.name ??
        "None picked")
      : "The standard image";

  return (
    <div className="flex flex-col gap-5">
      {!embedded && (
        <>
          <button
            type="button"
            onClick={onCancel}
            className="flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-(--gray-11) text-[12px] hover:text-(--gray-12)"
          >
            <ArrowLeft size={10} />
            <span>
              {plan.scope === "image"
                ? "Back to images"
                : "Back to environments"}
            </span>
          </button>

          <div className="flex flex-col gap-1">
            <Text className="font-medium text-(--gray-12) text-[15px]">
              {plan.scope === "image"
                ? "New sandbox image"
                : "Set up a cloud environment"}
            </Text>
            <Text className="max-w-[60ch] text-(--gray-11) text-[12.5px] leading-snug">
              {plan.scope === "image"
                ? "Built once and reused: any environment can start its sessions from this image."
                : "An environment is where cloud sessions run: the repositories they work on, what they may reach, and the image they start from."}
            </Text>
          </div>
        </>
      )}

      <div className="flex items-start gap-6">
        <div className="w-[124px] shrink-0 pt-0.5">
          <Stepper
            labels={steps.map((entry) => entry.label)}
            current={current}
            complete={complete}
            onSelect={setStep}
          />
        </div>
        <div className="min-h-[320px] min-w-0 flex-1">
          {currentKey === "environment" && (
            <EnvironmentStep
              plan={plan}
              environments={environments}
              onChange={onChange}
            />
          )}
          {currentKey === "access" && (
            <AccessStep plan={plan} onChange={onChange} />
          )}
          {currentKey === "image" && plan.scope === "image" && (
            <ImageDetailsStep plan={plan} onChange={onChange} />
          )}
          {currentKey === "image" && plan.scope === "environment" && (
            <BaseImageStep plan={plan} images={images} onChange={onChange} />
          )}
          {currentKey === "tools" && (
            <ToolsStep plan={plan} onChange={onChange} />
          )}
          {currentKey === "setup" && (
            <SetupStep
              plan={plan}
              onChange={onChange}
              onPickRepository={() => setStep(0)}
            />
          )}
          {currentKey === "review" && (
            <ReviewStep
              plan={plan}
              targetName={targetName}
              baseImageName={baseImageName}
            />
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 border-(--gray-4) border-t pt-4">
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {current > 0 && (
            <Button
              variant="link-muted"
              size="sm"
              onClick={() => setStep(current - 1)}
            >
              Back
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          {isLastStep ? (
            <SubmitButtons
              building={building}
              needsBuilder={needsBuilder}
              isNewEnvironment={plan.target === "new"}
              saving={saving}
              canSubmit={canSubmit}
              onSubmit={onSubmit}
            />
          ) : (
            <Button
              variant="primary"
              size="sm"
              disabled={complete[current] !== true}
              onClick={() => setStep(current + 1)}
            >
              Next
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Long enough that moving the pointer across the row doesn't flash a card. */
const CARD_OPEN_DELAY_MS = 250;
const CARD_CLOSE_DELAY_MS = 100;

function BuildModeCard({
  title,
  body,
  note,
  trigger,
}: {
  title: string;
  body: string;
  note: string;
  trigger: ReactElement;
}) {
  return (
    <PreviewCard.Root>
      <PreviewCard.Trigger
        delay={CARD_OPEN_DELAY_MS}
        closeDelay={CARD_CLOSE_DELAY_MS}
        render={trigger}
      />
      <PreviewCard.Portal>
        <PreviewCard.Positioner
          side="top"
          align="end"
          sideOffset={8}
          className="z-50"
        >
          <PreviewCard.Popup
            render={
              <Card
                size="sm"
                className="w-[17.5rem] origin-bottom gap-1.5 border border-border px-3 py-2.5 shadow-md transition-[opacity,transform] duration-150 data-[ending-style]:scale-[0.98] data-[starting-style]:scale-[0.98] data-[ending-style]:opacity-0 data-[starting-style]:opacity-0"
              />
            }
          >
            <span className="font-medium text-(--gray-12) text-[12px]">
              {title}
            </span>
            <span className="text-(--gray-11) text-[11.5px] leading-relaxed">
              {body}
            </span>
            <span className="text-(--gray-10) text-[11px] leading-snug">
              {note}
            </span>
          </PreviewCard.Popup>
        </PreviewCard.Positioner>
      </PreviewCard.Portal>
    </PreviewCard.Root>
  );
}

function SubmitButtons({
  building,
  needsBuilder,
  isNewEnvironment,
  saving,
  canSubmit,
  onSubmit,
}: {
  building: boolean;
  needsBuilder: boolean;
  isNewEnvironment: boolean;
  saving: boolean;
  canSubmit: boolean;
  onSubmit: (mode: ImageBuildMode | null) => void;
}) {
  if (!building) {
    return (
      <Button
        variant="primary"
        size="sm"
        loading={saving}
        disabled={!canSubmit}
        data-attr="environment-setup-save"
        onClick={() => onSubmit(null)}
      >
        {isNewEnvironment ? "Create environment" : "Save environment"}
      </Button>
    );
  }
  return (
    <>
      {/* A tool apt cannot install leaves the session as the only route, so it
          takes the primary button rather than sitting beside one that cannot
          deliver the image. */}
      <BuildModeCard
        title="Work it out in a session"
        body="The image is built in a session you can watch. Every install runs in front of you, so you can fix what fails and try again."
        note="The image is saved when the build works."
        trigger={
          <Button
            variant={needsBuilder ? "primary" : "outline"}
            size="sm"
            loading={saving}
            disabled={!canSubmit}
            data-attr="environment-setup-open-builder"
            onClick={() => onSubmit("builder")}
          >
            Work it out in a session
          </Button>
        }
      />
      {!needsBuilder && (
        <BuildModeCard
          title="Build it now"
          body="The image is built in the background from this plan. Nothing to watch, and nothing to answer while it runs."
          note="If an install fails, the build stops and keeps the log."
          trigger={
            <Button
              variant="primary"
              size="sm"
              loading={saving}
              disabled={!canSubmit}
              data-attr="environment-setup-build"
              onClick={() => onSubmit("build")}
            >
              Build it now
            </Button>
          }
        />
      )}
    </>
  );
}
