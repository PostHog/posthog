import type { Task } from "@posthog/shared/domain-types";
import { Flex, Text } from "@radix-ui/themes";
import type { WorktreeEntry } from "./WorktreeRow";
import { WorktreeRow } from "./WorktreeRow";

export interface WorktreeGroup {
  folderPath: string;
  worktrees: WorktreeEntry[];
}

function getFolderName(folderPath: string): string {
  const parts = folderPath.split("/");
  return parts[parts.length - 1] || folderPath;
}

interface WorktreeGroupSectionProps {
  group: WorktreeGroup;
  taskMap: Map<string, Task>;
  deletingWorktrees: Set<string>;
  onDelete: (
    worktreePath: string,
    allTaskIds: string[],
    existingTaskIds: string[],
    folderPath: string,
  ) => void;
}

export function WorktreeGroupSection({
  group,
  taskMap,
  deletingWorktrees,
  onDelete,
}: WorktreeGroupSectionProps) {
  const folderName = getFolderName(group.folderPath);

  return (
    <Flex direction="column">
      <Text color="gray" mb="2" className="text-[13px]">
        {folderName}
      </Text>
      <Flex direction="column">
        {group.worktrees.map((worktree, index) => (
          <WorktreeRow
            key={worktree.worktreePath}
            worktree={worktree}
            folderPath={group.folderPath}
            taskMap={taskMap}
            isDeleting={deletingWorktrees.has(worktree.worktreePath)}
            onDelete={onDelete}
            isLast={index === group.worktrees.length - 1}
          />
        ))}
      </Flex>
    </Flex>
  );
}
