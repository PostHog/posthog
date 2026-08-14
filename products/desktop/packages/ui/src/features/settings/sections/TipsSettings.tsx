import { Button } from "@posthog/quill";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import {
  resetTeachingTips,
  useRetiredTipCount,
} from "@posthog/ui/primitives/TeachingTip";
import { toast } from "@posthog/ui/primitives/toast";

/**
 * Puts back the tips someone turned off. Without this, "Don't show again" is
 * the only control a tip has and it cannot be undone.
 *
 * It sits with notifications rather than with appearance: both are the app
 * interrupting someone, and this is the page a person opens to stop that.
 */
export function TipsSection() {
  const retiredCount = useRetiredTipCount();
  return (
    <SettingsSection
      label="Tips"
      description="Tips point out a part of the app the first time it matters."
    >
      <SettingsCard>
        <SettingsCardRow
          label="Tips you've turned off"
          description={
            retiredCount === 0
              ? "You haven't turned any off."
              : `${retiredCount === 1 ? "1 tip" : `${retiredCount} tips`} won't be shown again.`
          }
        >
          <Button
            size="sm"
            variant="outline"
            disabled={retiredCount === 0}
            onClick={() => {
              resetTeachingTips();
              toast.success("Tips are back on");
            }}
          >
            Show tips again
          </Button>
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}
