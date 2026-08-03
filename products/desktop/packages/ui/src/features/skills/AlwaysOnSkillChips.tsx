import { Lightbulb, X } from "@phosphor-icons/react";
import type { ResolvedAlwaysOnSkill } from "@posthog/core/skills/alwaysOnSkills";
import { Tooltip } from "@radix-ui/themes";
import { openSettings } from "../settings/hooks/useOpenSettings";
import { useSkillsSelectionActions } from "./skillsSelectionStore";
import { setSkillAlwaysOnTracked } from "./useAlwaysOnSkill";

interface AlwaysOnSkillChipsProps {
  skills: ResolvedAlwaysOnSkill[];
}

// Chips for the skills that will be auto-injected into the next task
// (Settings → Skills "Always-on" toggles). Clicking a chip opens the skill in
// settings; the X turns its always-on toggle off — globally, not just for the
// task being composed.
export function AlwaysOnSkillChips({ skills }: AlwaysOnSkillChipsProps) {
  const { requestSkill } = useSkillsSelectionActions();
  if (skills.length === 0) return null;

  return (
    <>
      {skills.map((skill) => (
        <span
          key={`${skill.source}:${skill.name}`}
          className="inline-flex min-w-0 items-center gap-1 rounded-[var(--radius-1)] bg-[var(--gray-a3)] px-1.5 py-px font-medium text-[12px] text-[var(--gray-11)]"
        >
          <Tooltip
            content={`Always-on skill${skill.description ? `: ${skill.description}` : ""}`}
          >
            <button
              type="button"
              onClick={() => {
                requestSkill(skill.name);
                openSettings("skills");
              }}
              className="inline-flex min-w-0 items-center gap-1 rounded text-[var(--gray-11)] hover:text-gray-12"
            >
              <Lightbulb size={12} />
              <span className="truncate">/{skill.name}</span>
            </button>
          </Tooltip>
          <Tooltip content="Turn off always-on">
            <button
              type="button"
              onClick={() => setSkillAlwaysOnTracked(skill, false)}
              aria-label={`Turn off always-on for ${skill.name}`}
              className="ml-0.5 inline-flex size-3.5 items-center justify-center rounded text-gray-10 hover:bg-gray-5 hover:text-gray-12"
            >
              <X size={12} />
            </button>
          </Tooltip>
        </span>
      ))}
    </>
  );
}
