import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import {
  countRetiredHints,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";

/**
 * The switch over every tip, and a way back from the ones already hidden.
 *
 * It sits with notifications rather than with appearance: both are the app
 * interrupting someone, and notifications is the page a person opens to stop
 * that.
 */
export function TipsSection() {
  const enabled = useSettingsStore((state) => state.tipsEnabled);
  const setTipsEnabled = useSettingsStore((state) => state.setTipsEnabled);
  const resetHints = useSettingsStore((state) => state.resetHints);
  const retiredCount = useSettingsStore((state) =>
    countRetiredHints(state.hints),
  );

  return (
    <SettingsSection
      label="Tips"
      description="Short pointers that appear the first time a part of the app matters"
    >
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
              setTipsEnabled(checked);
            }}
          />
        </SettingsCardRow>

        <SettingsCardRow
          label="Reset tips"
          description={
            retiredCount === 0
              ? "Every tip is still showing"
              : retiredCount === 1
                ? "One tip has stopped showing"
                : `${retiredCount} tips have stopped showing`
          }
        >
          <Button
            size="sm"
            variant="outline"
            disabled={retiredCount === 0}
            onClick={() => {
              resetHints();
              toast.success("Tips are back");
            }}
          >
            Reset
          </Button>
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}
