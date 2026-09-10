import { TaskHeaderActions } from "@posthog/ui/features/task-detail/components/TaskHeaderActions";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import { useAppView } from "@posthog/ui/router/useAppView";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";

// The in-pane content header for the unified Bluebird chrome. Shows the active
// view's title (pushed into the header store by each view) on the left and that
// task's action row (TaskHeaderActions) on the right — the branch selector,
// review-panel toggle, skill buttons and task actions that
// used to live in the Code header bar.
//
// This breadcrumb row is scoped to views that name what you are looking at:
// task detail, the loop scenes (list / detail / form), which live outside the
// space routes but can belong to a space, and Self-driving with the reports it
// opens, whose list moved into the rail's sidebar and left the pane with no
// title of its own. Every other page drops it (the title bar search carries
// wayfinding instead). The /website (Channels) space keeps its own header
// (ShellLayout), so it's unaffected — this is mounted only outside it.
//
// A loop with no space pushes null, so the row collapses for it too: what a
// view puts in the header store decides, this only says who may.
const BREADCRUMB_VIEWS = new Set(["task-detail", "loops", "inbox", "report"]);

export function ContentHeader() {
  const content = useHeaderStore((state) => state.content);
  const view = useAppView();

  const activeTaskId = view.type === "task-detail" ? view.taskId : undefined;
  const { data: tasks } = useTasks();
  const activeTask = activeTaskId
    ? tasks?.find((t) => t.id === activeTaskId)
    : undefined;
  const showTaskSection = view.type === "task-detail" && Boolean(activeTask);

  if (!BREADCRUMB_VIEWS.has(view.type)) return null;

  if (!content && !showTaskSection) return null;

  return (
    <ChromeBar inset="control">
      {content && (
        <div className="flex h-full min-w-0 flex-1 items-center justify-between overflow-hidden">
          {content}
        </div>
      )}

      {showTaskSection && activeTask && <TaskHeaderActions task={activeTask} />}
    </ChromeBar>
  );
}
