import {
  Folder,
  Package,
  Robot,
  Storefront,
  User,
  Warning,
} from "@phosphor-icons/react";
import type {
  SkillAnalysis,
  SkillIssue,
} from "@posthog/core/skills/analyzeSkills";
import type { SkillInfo, SkillSource } from "@posthog/shared";
import { Badge, Flex, Text, Tooltip } from "@radix-ui/themes";
import { useEffect, useRef } from "react";
import { SkillListCard } from "./SkillListCard";

export const SOURCE_CONFIG: Record<
  SkillSource,
  { icon: typeof Package; label: string; sectionTitle: string }
> = {
  user: { icon: User, label: "User", sectionTitle: "Your skills" },
  bundled: {
    icon: Package,
    label: "PostHog",
    sectionTitle: "PostHog",
  },
  repo: { icon: Folder, label: "Repo", sectionTitle: "Repository" },
  marketplace: {
    icon: Storefront,
    label: "Marketplace",
    sectionTitle: "Marketplace",
  },
  codex: { icon: Robot, label: "Codex", sectionTitle: "Codex" },
};

interface SkillCardProps {
  skill: SkillInfo;
  isSelected: boolean;
  onClick: () => void;
  /** When true, scroll this card into view once (used for deep-linked skills). */
  scrollIntoView?: boolean;
  onScrolledIntoView?: () => void;
  issues?: SkillIssue[];
}

export function SkillCard({
  skill,
  isSelected,
  onClick,
  scrollIntoView,
  onScrolledIntoView,
  issues = [],
}: SkillCardProps) {
  const config = SOURCE_CONFIG[skill.source];
  const Icon = config?.icon ?? Package;

  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!scrollIntoView) return;
    ref.current?.scrollIntoView({ block: "center" });
    onScrolledIntoView?.();
  }, [scrollIntoView, onScrolledIntoView]);

  return (
    <SkillListCard
      cardRef={ref}
      icon={<Icon size={14} weight="duotone" className="text-gray-11" />}
      title={skill.name}
      subtitle={skill.description || undefined}
      isSelected={isSelected}
      onClick={onClick}
      trailing={
        <>
          {issues.length > 0 && (
            <Tooltip
              content={
                <Flex direction="column" gap="1">
                  {issues.map((issue) => (
                    <Text key={issue.message} size="1">
                      {issue.message}
                    </Text>
                  ))}
                </Flex>
              }
            >
              <Warning size={14} className="shrink-0 text-amber-11" />
            </Tooltip>
          )}
          {skill.repoName && (
            <Badge size="1" variant="soft" color="gray" className="shrink-0">
              {skill.repoName}
            </Badge>
          )}
        </>
      }
    />
  );
}

interface SkillSectionProps {
  title: string;
  skills: SkillInfo[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  scrollToPath: string | null;
  onScrolledIntoView: () => void;
  analysis?: SkillAnalysis;
}

export function SkillSection({
  title,
  skills,
  selectedPath,
  onSelect,
  scrollToPath,
  onScrolledIntoView,
  analysis,
}: SkillSectionProps) {
  return (
    <Flex direction="column" gap="1">
      <Text className="mb-1 font-medium text-[12px] text-gray-9 uppercase tracking-wider">
        {title}
      </Text>
      <Flex direction="column" gap="1">
        {skills.map((skill) => (
          <SkillCard
            key={skill.path}
            skill={skill}
            isSelected={selectedPath === skill.path}
            onClick={() => onSelect(skill.path)}
            scrollIntoView={scrollToPath === skill.path}
            onScrolledIntoView={onScrolledIntoView}
            issues={analysis?.[skill.path]}
          />
        ))}
      </Flex>
    </Flex>
  );
}
