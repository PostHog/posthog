import { useServiceOptional } from "@posthog/di/react";
import {
  type ITaskBrowserHost,
  TASK_BROWSER_HOST,
  type TaskBrowserPermissionDecision,
} from "@posthog/platform/task-browser";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { useTaskBrowserPermissionStore } from "./taskBrowserPermissionStore";
import { taskBrowserPromptCopy } from "./taskBrowserPromptCopy";
import { useTaskTitle } from "./useTaskTitle";

export function TaskBrowserPermissionDialog() {
  const host = useServiceOptional<ITaskBrowserHost>(TASK_BROWSER_HOST);
  const current = useTaskBrowserPermissionStore((state) => state.queue[0]);
  const remove = useTaskBrowserPermissionStore((state) => state.remove);
  const taskTitle = useTaskTitle(current?.taskId);
  if (!host || !current) return null;
  const copy = taskBrowserPromptCopy(current);
  const answer = (decision: TaskBrowserPermissionDecision) => {
    remove(current.requestId);
    void host.respondToPermission(current.requestId, decision);
  };

  return (
    <AlertDialog
      open
      onOpenChange={(open) => {
        if (!open) answer("deny");
      }}
    >
      <AlertDialogContent data-attr="task-browser-permission">
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.title}</AlertDialogTitle>
          <AlertDialogDescription>
            {taskTitle
              ? `In “${taskTitle}”: ${copy.description}`
              : copy.description}
          </AlertDialogDescription>
          {copy.detail && (
            <blockquote className="border-border border-l-2 pl-2 text-foreground text-xs">
              {copy.detail}
            </blockquote>
          )}
        </AlertDialogHeader>
        <AlertDialogFooter className="flex-wrap">
          {copy.actions.map((action) => (
            <Button
              key={action.decision}
              variant={action.variant}
              size="default"
              data-attr={`task-browser-permission-${action.decision}`}
              onClick={() => answer(action.decision)}
            >
              {action.label}
            </Button>
          ))}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
