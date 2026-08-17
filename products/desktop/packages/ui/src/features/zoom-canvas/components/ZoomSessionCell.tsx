import { useQuery } from "@tanstack/react-query";
import { TaskDetailSkeleton } from "../../../router/routeSkeletons";
import { TaskDetail } from "../../task-detail/components/TaskDetail";
import { taskDetailQuery } from "../../tasks/queries";
import { pickFreshestTask } from "../../tasks/taskFreshness";
import { useTasks } from "../../tasks/useTasks";

/**
 * The selected cell, rendered as the real task: the same {@link TaskDetail} the
 * task route mounts, panels and all. Only ever one of these is on the canvas —
 * everything else is a preview — so the cost is the cost of the task view the
 * user was going to open anyway.
 *
 * Resolving the full task here mirrors the task route: the list copy appears
 * immediately, and the detail fetch converges it on the server's latest run.
 */
export function ZoomSessionCell({ taskId }: { taskId: string }) {
  const { data: tasks } = useTasks();
  const fromList = tasks?.find((task) => task.id === taskId);
  const { data: fetched } = useQuery(taskDetailQuery(taskId));
  const task = pickFreshestTask(fetched, fromList);

  if (!task) return <TaskDetailSkeleton />;
  return <TaskDetail task={task} />;
}
