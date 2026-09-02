import { parseCloneProgress } from "@posthog/core/clone/cloneProgress";
import {
  findCloneForRepo,
  isRepoCloning,
} from "@posthog/core/clone/cloneSelectors";
import { getTaskRepository } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useWorkspaceTRPC } from "@posthog/workspace-client/trpc";
import { useQuery } from "@tanstack/react-query";
import { cloneStore } from "../../clone/cloneStore";
import { useWorkspace } from "../../workspace/useWorkspace";
import { useRefreshedTask } from "./useRefreshedTask";

interface UseTaskDataParams {
  taskId: string;
  initialTask: Task;
}

export function useTaskData({ taskId, initialTask }: UseTaskDataParams) {
  const trpcReact = useWorkspaceTRPC();
  const task = useRefreshedTask(taskId, initialTask);

  const workspace = useWorkspace(taskId);
  const repoPath = workspace?.folderPath ?? null;

  const { data: repoExists } = useQuery(
    trpcReact.git.validateRepo.queryOptions(
      { directoryPath: repoPath ?? "" },
      { enabled: !!repoPath },
    ),
  );

  const repository = getTaskRepository(task);

  const isCloning = cloneStore((state) =>
    repository ? isRepoCloning(state.operations, repository) : false,
  );

  const cloneProgress = cloneStore(
    (state) =>
      repository
        ? parseCloneProgress(findCloneForRepo(state.operations, repository))
        : null,
    (a, b) => a?.message === b?.message && a?.percent === b?.percent,
  );

  return {
    task,
    repoPath,
    repoExists: repoExists ?? null,
    isCloning,
    cloneProgress,
  };
}
