import {
  isAlwaysOnSkill,
  isAlwaysOnSkillSource,
} from "@posthog/core/skills/alwaysOnSkills";
import type { SkillInfo } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useCallback } from "react";
import { track } from "../../shell/analytics";
import { useSettingsStore } from "../settings/settingsStore";

/** Store write + analytics in one place, callable outside React (chips). */
export function setSkillAlwaysOnTracked(
  skill: Pick<SkillInfo, "name" | "source">,
  enabled: boolean,
): void {
  useSettingsStore.getState().setSkillAlwaysOn(skill, enabled);
  track(ANALYTICS_EVENTS.SKILL_ALWAYS_ON_TOGGLED, {
    skill_source: skill.source,
    enabled,
    total_always_on: useSettingsStore.getState().alwaysOnSkills.length,
  });
}

/** Read + toggle a skill's always-on state (Settings-store backed). */
export function useAlwaysOnSkill(skill: Pick<SkillInfo, "name" | "source">) {
  const alwaysOnSkills = useSettingsStore((s) => s.alwaysOnSkills);

  const canToggle = isAlwaysOnSkillSource(skill.source);
  const enabled = canToggle && isAlwaysOnSkill(alwaysOnSkills, skill);

  const setEnabled = useCallback(
    (next: boolean) => setSkillAlwaysOnTracked(skill, next),
    [skill],
  );

  return { canToggle, enabled, setEnabled };
}
