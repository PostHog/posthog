import {
  Folder,
  Lightbulb,
  Package,
  Robot,
  Storefront,
  Warning,
} from "@phosphor-icons/react";
import type {
  SkillAnalysis,
  SkillIssue,
} from "@posthog/core/skills/analyzeSkills";
import { Switch } from "@posthog/quill";
import type { SkillInfo, SkillSource } from "@posthog/shared";
import { Badge, Flex, Text, Tooltip } from "@radix-ui/themes";
import { useEffect, useRef } from "react";
import { SkillListCard } from "./SkillListCard";
import { useSetSkillEnabled } from "./useSkillMutations";

export const SOURCE_CONFIG: Record<
  SkillSource,
  {
    icon: typeof Package;
    label: string;
    sectionTitle: string;
    chipClass: string;
  }
> = {
  user: {
    icon: Lightbulb,
    label: "User",
    sectionTitle: "Your skills",
    chipClass: "bg-amber-3 text-amber-11",
  },
  bundled: {
    icon: Package,
    label: "PostHog",
    sectionTitle: "PostHog",
    chipClass: "bg-orange-3 text-orange-11",
  },
  repo: {
    icon: Folder,
    label: "Repo",
    sectionTitle: "Repository",
    chipClass: "bg-green-3 text-green-11",
  },
  marketplace: {
    icon: Storefront,
    label: "Marketplace",
    sectionTitle: "Marketplace",
    chipClass: "bg-blue-3 text-blue-11",
  },
  codex: {
    icon: Robot,
    label: "Codex",
    sectionTitle: "Codex",
    chipClass: "bg-violet-3 text-violet-11",
  },
};

interface SkillCardProps {
  skill: SkillInfo;
  isSelected: boolean;
  /** Hidden when every skill in the section comes from the same repo. */
  showRepoBadge?: boolean;
  onClick: () => void;
  /** When true, scroll this card into view once (used for deep-linked skills). */
  scrollIntoView?: boolean;
  onScrolledIntoView?: () => void;
  issues?: SkillIssue[];
}

function formatTokens(bytes: number): string {
  const tokens = Math.max(1, Math.round(bytes / 4));
  return tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : `${tokens}`;
}

export function SkillCard({
  skill,
  isSelected,
  showRepoBadge = true,
  onClick,
  scrollIntoView,
  onScrolledIntoView,
  issues = [],
}: SkillCardProps) {
  const config = SOURCE_CONFIG[skill.source];
  const Icon = config?.icon ?? Package;
  const setEnabled = useSetSkillEnabled();
  const isEnabled = skill.enabled !== false;

  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!scrollIntoView) return;
    ref.current?.scrollIntoView({ block: "center" });
    onScrolledIntoView?.();
  }, [scrollIntoView, onScrolledIntoView]);

  return (
    <SkillListCard
      cardRef={ref}
      icon={<Icon size={14} weight="duotone" />}
      iconClass={config?.chipClass}
      title={skill.name}
      subtitle={
        skill.description && skill.description !== skill.name
          ? skill.description
          : undefined
      }
      isSelected={isSelected}
      dimmed={!isEnabled}
      onClick={onClick}
      trailing={
        <>
          <Tooltip
            content={`About ${formatTokens(skill.skillMdBytes)} tokens when the agent loads it. Skills load on demand.`}
          >
            <Text className="shrink-0 text-[11px] text-gray-8">
              ≈{formatTokens(skill.skillMdBytes)} tok
            </Text>
          </Tooltip>
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
          {skill.repoName && showRepoBadge && (
            <Badge size="1" variant="soft" color="gray" className="shrink-0">
              {skill.repoName}
            </Badge>
          )}
          {skill.disableModelInvocation && (
            <Tooltip content="The agent won't use this skill on its own. It runs only when you invoke it">
              <Badge size="1" variant="soft" color="gray" className="shrink-0">
                Manual
              </Badge>
            </Tooltip>
          )}
          {!isEnabled && (
            <Badge size="1" variant="soft" color="gray" className="shrink-0">
              Off
            </Badge>
          )}
          {skill.editable && skill.source !== "repo" && (
            <Tooltip
              content={
                isEnabled
                  ? "On. Agents can discover and use this skill."
                  : "Off. Agents do not see this skill."
              }
            >
              {/* biome-ignore lint/a11y/noStaticElementInteractions: stops row selection when toggling */}
              <span
                className="flex shrink-0 items-center"
                onClick={(event) => event.stopPropagation()}
                onKeyDown={(event) => event.stopPropagation()}
              >
                <Switch
                  checked={isEnabled}
                  disabled={setEnabled.isPending}
                  aria-label={`Turn ${skill.name} ${isEnabled ? "off" : "on"}`}
                  onCheckedChange={(checked) =>
                    setEnabled.mutate({
                      skillPath: skill.path,
                      enabled: checked,
                    })
                  }
                />
              </span>
            </Tooltip>
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
  /** Skips the section title (e.g. when a source chip already names it). */
  hideHeader?: boolean;
}

export function SkillSection({
  title,
  skills,
  selectedPath,
  onSelect,
  scrollToPath,
  onScrolledIntoView,
  analysis,
  hideHeader,
}: SkillSectionProps) {
  const repoNames = new Set(
    skills.map((skill) => skill.repoName).filter(Boolean),
  );
  const sharedRepo = repoNames.size === 1 ? [...repoNames][0] : undefined;
  return (
    <Flex direction="column" gap="1">
      {hideHeader ? null : (
        <Flex align="center" gap="2" className="mb-1">
          <Text className="font-medium text-[12px] text-gray-9 uppercase tracking-wider">
            {title}
            {sharedRepo ? ` · ${sharedRepo}` : ""}
          </Text>
          <Text className="text-[11px] text-gray-8">{skills.length}</Text>
        </Flex>
      )}
      <Flex direction="column" gap="1">
        {skills.map((skill) => (
          <SkillCard
            key={skill.path}
            skill={skill}
            showRepoBadge={!sharedRepo}
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
