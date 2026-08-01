import { UsersThree } from "@phosphor-icons/react";
import type { TeamSkillInfo } from "@posthog/core/skills/teamSkillsService";
import { Badge, Flex } from "@radix-ui/themes";
import { SkillListCard } from "./SkillListCard";

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
    <Flex direction="column" gap="1">
      {skills.map((skill) => (
        <SkillListCard
          key={skill.id}
          icon={
            <UsersThree size={14} weight="duotone" className="text-gray-11" />
          }
          title={skill.name}
          subtitle={skill.description || undefined}
          isSelected={selectedName === skill.name}
          onClick={() => onSelect(skill)}
          trailing={
            <>
              {skill.installedLocally && (
                <Badge
                  size="1"
                  variant="soft"
                  color="green"
                  className="shrink-0"
                >
                  Installed
                </Badge>
              )}
              <Badge size="1" variant="soft" color="gray" className="shrink-0">
                v{skill.version}
              </Badge>
            </>
          }
        />
      ))}
    </Flex>
  );
}
