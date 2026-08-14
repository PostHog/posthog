import { GitBranch, Spinner, TreeStructure } from "@phosphor-icons/react";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { SidebarSection } from "@posthog/ui/features/sidebar/components/SidebarSection";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useAdoptableWorktrees } from "@posthog/ui/features/sidebar/useAdoptableWorktrees";
import { useStartTaskFromWorktree } from "@posthog/ui/features/sidebar/useStartTaskFromWorktree";

interface GroupWorktreesSectionProps {
  groupId: string;
  mainRepoPath: string;
}

/**
 * Nested "Worktrees" dropdown at the bottom of a repo group listing the repo's
 * task-less worktrees. Clicking one starts a task in that worktree and opens
 * its chat + shell. Renders nothing when the repo has no adoptable worktrees.
 */
export function GroupWorktreesSection({
  groupId,
  mainRepoPath,
}: GroupWorktreesSectionProps) {
  const worktrees = useAdoptableWorktrees(mainRepoPath);
  const collapsedSections = useSidebarStore((state) => state.collapsedSections);
  const toggleSection = useSidebarStore((state) => state.toggleSection);
  const { startTask, startingBranches } =
    useStartTaskFromWorktree(mainRepoPath);

  if (worktrees.length === 0) return null;

  const sectionId = `worktrees:${groupId}`;
  return (
    <SidebarSection
      id={sectionId}
      label={`Worktrees (${worktrees.length})`}
      icon={<TreeStructure size={14} className="text-gray-10" />}
      depth={1}
      isExpanded={!collapsedSections.has(sectionId)}
      onToggle={() => toggleSection(sectionId)}
      tooltipContent="Worktrees without a task — click one to start a task there"
    >
      {worktrees.map((worktree) => {
        const isStarting = startingBranches.has(worktree.branch);
        return (
          <SidebarItem
            key={worktree.worktreePath}
            depth={2}
            icon={<GitBranch size={14} />}
            label={worktree.branch}
            isDimmed={isStarting}
            disabled={isStarting}
            endContent={
              isStarting ? (
                <Spinner size={12} className="animate-spin text-gray-10" />
              ) : undefined
            }
            onClick={() => void startTask(worktree.branch)}
          />
        );
      })}
    </SidebarSection>
  );
}
