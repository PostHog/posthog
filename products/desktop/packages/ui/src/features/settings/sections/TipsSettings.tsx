import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import {
  resetTeachingTips,
  setTeachingTipsEnabled,
  useRetiredTipCount,
  useTipsEnabled,
} from "@posthog/ui/primitives/TeachingTip";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";

/**
 * The switch over every tip, and a way back from the ones already answered.
 *
 * It sits with notifications rather than with appearance: both are the app
 * interrupting someone, and notifications is the page a person opens to stop
 * that.
 */
export function TipsSection() {
  const enabled = useTipsEnabled();
  const retiredCount = useRetiredTipCount();

  return (
    <SettingsSection label="Tips">
      <SettingsCard>
        <SettingsCardRow
          label="Tips"
          description="Point out a part of the app the first time it matters"
        >
          <Switch
            size="sm"
            checked={enabled}
            onCheckedChange={(checked) => {
              track(ANALYTICS_EVENTS.SETTING_CHANGED, {
                setting_name: "teaching_tips",
                new_value: checked,
                old_value: enabled,
              });
              setTeachingTipsEnabled(checked);
            }}
          />
        </SettingsCardRow>

        <SettingsCardRow
          label="Reset tips"
          description={
            retiredCount === 0
              ? "You haven't dismissed any for good"
              : retiredCount === 1
                ? "Show the one you've dismissed for good"
                : `Show the ${retiredCount} you've dismissed for good`
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
            Reset
          </Button>
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}
