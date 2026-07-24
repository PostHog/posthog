import { TaskHeaderActions } from "@posthog/ui/features/task-detail/components/TaskHeaderActions";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useAppView } from "@posthog/ui/router/useAppView";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";
import { Flex } from "@radix-ui/themes";

// The in-pane content header for the unified Bluebird chrome. Shows the active
// view's title (pushed into the header store by each view) on the left and that
// task's action row (TaskHeaderActions) on the right — the branch selector,
// review-panel toggle, cloud/local handoff, skill buttons and task actions that
// used to live in the Code header bar.
//
// This breadcrumb row is now scoped to the task-detail view only: every other
// page drops it (the title bar search carries wayfinding instead). The /website
// (Channels) space keeps its own header (WebsiteLayout), so it's unaffected —
// this is mounted only outside it.
export function ContentHeader() {
  const content = useHeaderStore((state) => state.content);
  const view = useAppView();

  const activeTaskId = view.type === "task-detail" ? view.taskId : undefined;
  const { data: tasks } = useTasks();
  const activeTask = activeTaskId
    ? tasks?.find((t) => t.id === activeTaskId)
    : undefined;
  const showTaskSection = view.type === "task-detail" && Boolean(activeTask);

  // Only the task-detail view keeps the breadcrumb row.
  if (view.type !== "task-detail") return null;

  if (!content && !showTaskSection) return null;

  return (
    <Flex align="center" className="h-10 shrink-0 border-border border-b px-3">
      {content && (
        <Flex
          align="center"
          justify="between"
          className="h-full min-w-0 flex-1 overflow-hidden"
        >
          {content}
        </Flex>
      )}

      {showTaskSection && activeTask && <TaskHeaderActions task={activeTask} />}
    </Flex>
  );
}
