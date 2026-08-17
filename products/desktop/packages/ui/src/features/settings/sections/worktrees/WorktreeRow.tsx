import { Trash } from "@phosphor-icons/react";
import type { Task } from "@posthog/shared/domain-types";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { Button, Flex, Text } from "@radix-ui/themes";
import { DotsCircleSpinner } from "../../../../primitives/DotsCircleSpinner";
import { WorktreeSize } from "./WorktreeSize";

export interface WorktreeEntry {
  worktreePath: string;
  head: string;
  branch: string | null;
  taskIds: string[];
}

function getTaskTitle(task: Task): string {
  return task.title || task.description?.slice(0, 50) || task.id;
}

interface WorktreeRowProps {
  worktree: WorktreeEntry;
  folderPath: string;
  taskMap: Map<string, Task>;
  isDeleting: boolean;
  isLast: boolean;
  onDelete: (
    worktreePath: string,
    allTaskIds: string[],
    existingTaskIds: string[],
    folderPath: string,
  ) => void;
}

export function WorktreeRow({
  worktree,
  folderPath,
  taskMap,
  isDeleting,
  isLast,
  onDelete,
}: WorktreeRowProps) {
  const linkedTasks = worktree.taskIds
    .map((id) => taskMap.get(id))
    .filter((task): task is Task => task !== undefined);

  const handleTaskClick = (task: Task) => {
    closeSettings();
    void openTask(task);
  };

  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      py="3"
      style={{
        borderBottom: isLast ? undefined : "1px solid var(--gray-4)",
      }}
    >
      <Flex direction="column" gap="1" className="min-w-0 flex-1">
        <Text className="break-all text-[13px]">
          {worktree.worktreePath}
          <WorktreeSize worktreePath={worktree.worktreePath} />
        </Text>
        {linkedTasks.length > 0 ? (
          <Flex gap="1" wrap="wrap">
            {linkedTasks.map((task) => (
              <button
                key={task.id}
                type="button"
                onClick={() => handleTaskClick(task)}
                className="cursor-pointer truncate border-0 bg-transparent p-0 text-left text-[12px] text-gray-10 hover:text-accent-11 hover:underline"
              >
                {getTaskTitle(task)}
              </button>
            ))}
          </Flex>
        ) : (
          <span className="text-[12px] text-gray-10">No linked tasks</span>
        )}
      </Flex>
      <Button
        variant="outline"
        color="red"
        size="1"
        disabled={isDeleting}
        onClick={() =>
          onDelete(
            worktree.worktreePath,
            worktree.taskIds,
            linkedTasks.map((t) => t.id),
            folderPath,
          )
        }
      >
        {isDeleting ? <DotsCircleSpinner size={12} /> : <Trash size={12} />}
        Delete
      </Button>
    </Flex>
  );
}
