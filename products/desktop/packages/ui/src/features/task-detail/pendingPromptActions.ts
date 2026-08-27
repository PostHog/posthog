import { pendingPromptToContent } from "@posthog/core/tasks/pendingPrompts";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { pendingTaskPromptStoreApi } from "@posthog/ui/shell/pendingTaskPromptStore";

/**
 * Drop an interrupted prompt back into the new-task composer, then clear its
 * record. Copy-then-delete: the content is handed to the composer before the
 * durable record is removed, so a crash mid-recovery never loses the prompt.
 * Returns false when the record is already gone (nothing to recover).
 */
export function recoverPendingPrompt(key: string): boolean {
  const record = pendingTaskPromptStoreApi.get(key);
  if (!record) return false;
  openTaskInput({ initialContent: pendingPromptToContent(record) });
  pendingTaskPromptStoreApi.clear(key);
  return true;
}

/** Discard an interrupted prompt and open a fresh, empty new-task composer. */
export function discardPendingPrompt(key: string): void {
  pendingTaskPromptStoreApi.clear(key);
  openTaskInput();
}
