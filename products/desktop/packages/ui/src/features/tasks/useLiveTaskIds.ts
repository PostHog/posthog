import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

/**
 * The sessions that still exist, as a set.
 *
 * Command Center cells are persisted and only pruned when a session is
 * archived, so a deleted one's id lingers in the array and the grid draws that
 * tile empty. Anything reasoning about which tiles are free has to see the same
 * empty tile the user does. `null` while the list is unknown, which callers
 * read as "hold every non-empty cell" rather than guessing the other way.
 */
export function useLiveTaskIds(): ReadonlySet<string> | null {
  const { data: liveTasks } = useTasks();
  return useMemo(
    () => (liveTasks ? new Set(liveTasks.map((task) => task.id)) : null),
    [liveTasks],
  );
}
