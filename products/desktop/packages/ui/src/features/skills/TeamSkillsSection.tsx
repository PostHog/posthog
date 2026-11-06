import { UsersThreeIcon } from "@phosphor-icons/react";
import type { TeamSkillInfo } from "@posthog/core/skills/teamSkillsService";
import { SkillListCard } from "./SkillListCard";
import { SkillChip } from "./SkillPanelHeader";

interface TeamSkillsSectionProps {
  skills: TeamSkillInfo[];
  selectedName: string | null;
  onSelect: (skill: TeamSkillInfo) => void;
}

/** Skill cards shared via PostHog cloud, read-only here. */
export function TeamSkillsSection({
  skills,
  selectedName,
  onSelect,
}: TeamSkillsSectionProps) {
  return (
    <div className="flex flex-col gap-0.5">
      {skills.map((skill) => (
        <SkillListCard
          key={skill.id}
          icon={<UsersThreeIcon size={12} weight="duotone" />}
          title={skill.name}
          subtitle={skill.description || undefined}
          isSelected={selectedName === skill.name}
          onClick={() => onSelect(skill)}
          trailing={
            <>
              {skill.installedLocally && (
                <SkillChip tone="positive">Installed</SkillChip>
              )}
              <SkillChip>v{skill.version}</SkillChip>
            </>
          }
        />
      ))}
    </div>
  );
}
