import { useSuspendedTaskIds } from "../suspension/useSuspendedTaskIds";
import { useWorkspace } from "../workspace/useWorkspace";

export function useCwd(taskId: string): string | undefined {
  const workspace = useWorkspace(taskId);
  const suspendedIds = useSuspendedTaskIds();

  if (!workspace) return undefined;
  if (suspendedIds.has(taskId)) return undefined;

  return workspace.worktreePath ?? workspace.folderPath;
}
