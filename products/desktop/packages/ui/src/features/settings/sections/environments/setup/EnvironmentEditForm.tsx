import { ArrowLeft, Trash } from "@phosphor-icons/react";
import {
  type EnvironmentSetupPlan,
  stepError,
} from "@posthog/core/settings/environmentSetup";
import { Button, Text } from "@posthog/quill";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { AccessStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/AccessStep";
import { BaseImageStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/BaseImageStep";
import { EnvironmentStep } from "@posthog/ui/features/settings/sections/environments/setup/steps/EnvironmentStep";
import type { ReactNode } from "react";

interface EnvironmentEditFormProps {
  plan: EnvironmentSetupPlan;
  onChange: (plan: EnvironmentSetupPlan) => void;
  images: readonly SandboxCustomImage[];
  /** The name shown in the heading, which a rename must not change mid-edit. */
  environmentName: string;
  variablesAlreadySet: boolean;
  saving: boolean;
  deleting: boolean;
  onCancel: () => void;
  onSave: () => void;
  onArchive: () => void;
  /** Leaves for the image flow; an image is not created from inside this form. */
  onBuildNewImage: () => void;
  /** True while the form holds changes a navigation away would lose. */
  dirty: boolean;
}

/**
 * An existing environment, with the same fields the setup flow asks for but
 * all at once: someone editing knows what they came to change, so stepping
 * through the parts they did not come for is in the way.
 */
export function EnvironmentEditForm({
  plan,
  onChange,
  images,
  environmentName,
  variablesAlreadySet,
  saving,
  deleting,
  onCancel,
  onSave,
  onArchive,
  onBuildNewImage,
  dirty,
}: EnvironmentEditFormProps) {
  const error =
    stepError(plan, "environment") ??
    stepError(plan, "access") ??
    stepError(plan, "image");

  return (
    <div className="flex flex-col gap-5">
      <button
        type="button"
        onClick={onCancel}
        className="flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-(--gray-11) text-[12px] hover:text-(--gray-12)"
      >
        <ArrowLeft size={10} />
        <span>Back to environments</span>
      </button>

      <div className="flex flex-col gap-1">
        <Text className="font-medium text-(--gray-12) text-[15px]">
          {environmentName}
        </Text>
        <Text className="max-w-[60ch] text-(--gray-11) text-[12.5px] leading-snug">
          Changes take effect on the next session that starts here. Sessions
          already running keep what they have.
        </Text>
      </div>

      <div className="flex flex-col gap-5 rounded-(--radius-4) border border-(--gray-5) bg-(--color-panel-solid) px-5 py-4">
        <Section>
          <EnvironmentStep
            editing
            plan={plan}
            environments={[]}
            onChange={onChange}
          />
        </Section>
        <Section>
          <AccessStep
            plan={plan}
            onChange={onChange}
            variablesAlreadySet={variablesAlreadySet}
          />
        </Section>
        {plan.customImages && (
          <Section>
            <BaseImageStep
              plan={plan}
              images={images}
              onChange={onChange}
              onBuildNewImage={onBuildNewImage}
              buildNewDisabledReason={
                dirty ? "Save your changes first, then build one." : null
              }
            />
          </Section>
        )}
      </div>

      <div className="flex items-center gap-3 border-(--gray-4) border-t pt-4">
        <Button
          variant="link-muted"
          size="sm"
          loading={deleting}
          disabled={deleting || saving}
          data-attr="environment-edit-archive"
          onClick={onArchive}
        >
          <Trash size={13} />
          Archive
        </Button>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {error && (
            <Text className="text-(--amber-11) text-[11.5px]">{error}</Text>
          )}
          <Button variant="outline" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={saving}
            disabled={saving || deleting || error !== null}
            data-attr="environment-edit-save"
            onClick={onSave}
          >
            Save changes
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Each part of the environment, divided so the page reads as a list of them. */
function Section({ children }: { children: ReactNode }) {
  return (
    <div className="border-(--gray-4) border-t border-dashed pt-5 first-of-type:border-t-0 first-of-type:pt-0">
      {children}
    </div>
  );
}
