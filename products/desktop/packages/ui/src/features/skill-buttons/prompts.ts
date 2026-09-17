import {
  Broadcast,
  ChartBar,
  Flask,
  type Icon,
  Pulse,
  ToggleRight,
  Warning,
} from "@phosphor-icons/react";
import {
  SKILL_BUTTON_CATALOG,
  type SkillButtonCatalogEntry,
  type SkillButtonId,
} from "@posthog/core/skill-buttons/catalog";
import { extractSkillButtonId } from "@posthog/core/skill-buttons/prompts";

export { extractSkillButtonId };
export type { SkillButtonId };

interface SkillButton extends SkillButtonCatalogEntry {
  Icon: Icon;
}

const SKILL_BUTTON_ICONS: Record<SkillButtonId, Icon> = {
  "add-analytics": ChartBar,
  "create-feature-flags": ToggleRight,
  "run-experiment": Flask,
  "add-error-tracking": Warning,
  "instrument-llm-calls": Broadcast,
  "add-logging": Pulse,
};

export const SKILL_BUTTONS: Record<SkillButtonId, SkillButton> =
  Object.fromEntries(
    (Object.keys(SKILL_BUTTON_CATALOG) as SkillButtonId[]).map((id) => [
      id,
      { ...SKILL_BUTTON_CATALOG[id], Icon: SKILL_BUTTON_ICONS[id] },
    ]),
  ) as Record<SkillButtonId, SkillButton>;
