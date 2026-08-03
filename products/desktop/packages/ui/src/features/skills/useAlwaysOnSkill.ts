import {
  isAlwaysOnSkill,
  isAlwaysOnSkillSource,
} from "@posthog/core/skills/alwaysOnSkills";
import type { SkillInfo } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useCallback } from "react";
import { track } from "../../shell/analytics";
import { useSettingsStore } from "../settings/settingsStore";

/** Read + toggle a skill's always-on state (Settings-store backed). */
export function useAlwaysOnSkill(skill: Pick<SkillInfo, "name" | "source">) {
  const alwaysOnSkills = useSettingsStore((s) => s.alwaysOnSkills);
  const setSkillAlwaysOn = useSettingsStore((s) => s.setSkillAlwaysOn);

  const canToggle = isAlwaysOnSkillSource(skill.source);
  const enabled = canToggle && isAlwaysOnSkill(alwaysOnSkills, skill);

  const setEnabled = useCallback(
    (next: boolean) => {
      setSkillAlwaysOn(skill, next);
      track(ANALYTICS_EVENTS.SKILL_ALWAYS_ON_TOGGLED, {
        skill_source: skill.source,
        enabled: next,
        total_always_on: useSettingsStore.getState().alwaysOnSkills.length,
      });
    },
    [setSkillAlwaysOn, skill],
  );

  return { canToggle, enabled, setEnabled };
}
