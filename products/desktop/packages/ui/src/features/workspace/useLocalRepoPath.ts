import { resolveLocalRepoPath } from "@posthog/core/workspace/localRepoPath";
import { selectIsFocusedOnWorktree, useFocusStore } from "../focus/focusStore";
import { useWorkspace } from "./useWorkspace";

export function useLocalRepoPath(taskId: string): string | undefined {
  const workspace = useWorkspace(taskId);
  const isFocused = useFocusStore(
    selectIsFocusedOnWorktree(workspace?.worktreePath ?? ""),
  );
  return resolveLocalRepoPath(workspace, isFocused);
}
