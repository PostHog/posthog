import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { isTaskDetailNotFoundError } from "@posthog/ui/features/tasks/queries";
import { toast } from "@posthog/ui/primitives/toast";

/**
 * Report a failure to open a task the user asked for, by deep link or by the
 * "View task" action on the unarchive toast.
 *
 * A 404 says the task is not there yet rather than broken, because optimistic
 * and cloud-pending tasks are not returnable by the API until they sync. Every
 * other failure goes through `toastError`, which keeps the raw payload behind
 * the toast's "View larger" action instead of printing it as the title.
 *
 * Pass `status` when the caller only holds a flattened error string.
 */
export function toastOpenTaskError(error: unknown, status?: number): void {
  if (status === 404 || isTaskDetailNotFoundError(error)) {
    // An error toast, not a warning: warnings are suppressed when a user turns
    // toast notifications off, and a click that opened nothing must say so.
    toast.error(
      "This task is not available yet",
      "It may still be syncing. Try again in a moment.",
    );
    return;
  }
  toastError("Failed to open task", error);
}
