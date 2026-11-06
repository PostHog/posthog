import {
  FolderIcon,
  LightbulbIcon,
  PackageIcon,
  RobotIcon,
  StorefrontIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import type { SkillIssue } from "@posthog/core/skills/analyzeSkills";
import {
  Switch,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SkillInfo, SkillSource } from "@posthog/shared";
import { useEffect, useRef } from "react";
import { SkillListCard } from "./SkillListCard";
import { SkillChip } from "./SkillPanelHeader";
import { useSetSkillEnabled } from "./useSkillMutations";

export const SOURCE_CONFIG: Record<
  SkillSource,
  {
    icon: typeof PackageIcon;
    label: string;
    sectionTitle: string;
    chipClass: string;
    dotClass: string;
  }
> = {
  user: {
    icon: LightbulbIcon,
    label: "User",
    sectionTitle: "Your skills",
    chipClass: "bg-amber-3 text-amber-11",
    dotClass: "bg-amber-9",
  },
  bundled: {
    icon: PackageIcon,
    label: "PostHog",
    sectionTitle: "PostHog",
    chipClass: "bg-orange-3 text-orange-11",
    dotClass: "bg-orange-9",
  },
  repo: {
    icon: FolderIcon,
    label: "Repo",
    sectionTitle: "Repository",
    chipClass: "bg-green-3 text-green-11",
    dotClass: "bg-green-9",
  },
  marketplace: {
    icon: StorefrontIcon,
    label: "Marketplace",
    sectionTitle: "Marketplace",
    chipClass: "bg-blue-3 text-blue-11",
    dotClass: "bg-blue-9",
  },
  codex: {
    icon: RobotIcon,
    label: "Codex",
    sectionTitle: "Codex",
    chipClass: "bg-violet-3 text-violet-11",
    dotClass: "bg-violet-9",
  },
};

interface SkillCardProps {
  skill: SkillInfo;
  isSelected: boolean;
  showRepoBadge?: boolean;
  onClick: () => void;
  /** When true, scroll this card into view once (used for deep-linked skills). */
  scrollIntoView?: boolean;
  onScrolledIntoView?: () => void;
  issues?: SkillIssue[];
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
  const Icon = config?.icon ?? PackageIcon;
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
      icon={<Icon size={12} weight="duotone" />}
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
          {issues.length > 0 && (
            <WarningIcon
              size={13}
              className="shrink-0 text-amber-11"
              aria-label="This skill has issues"
            />
          )}
          {skill.repoName && showRepoBadge && (
            <SkillChip>{skill.repoName}</SkillChip>
          )}
          {skill.disableModelInvocation && <SkillChip>Manual</SkillChip>}
          {skill.editable && skill.source !== "repo" && (
            <Tooltip>
              <TooltipTrigger
                render={<span className="flex shrink-0 items-center" />}
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
              </TooltipTrigger>
              <TooltipContent>
                {isEnabled
                  ? "On. Agents can discover and use this skill."
                  : "Off. Agents do not see this skill."}
              </TooltipContent>
            </Tooltip>
          )}
        </>
      }
    />
  );
}
