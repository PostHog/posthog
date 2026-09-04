import { pendingPromptToContent } from "@posthog/core/tasks/pendingPrompts";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { pendingTaskPromptStoreApi } from "@posthog/ui/shell/pendingTaskPromptStore";

/**
 * Drop an interrupted prompt back into the new-task composer. The durable
 * record is kept and handed to the composer as `recoveredFromKey`; the composer
 * clears it only once it has applied the content (see TaskInput). So a crash
 * before the composer mounts leaves the record intact for the next launch to
 * recover, never a cleared record whose content lived only in memory.
 * Returns false when the record is already gone (nothing to recover).
 */
export function recoverPendingPrompt(key: string): boolean {
  const record = pendingTaskPromptStoreApi.get(key);
  if (!record) return false;
  openTaskInput({
    initialContent: pendingPromptToContent(record),
    recoveredFromKey: key,
    // Reopen in the space the prompt was submitted in, not whatever is current.
    ...(record.channelId
      ? { channelId: record.channelId }
      : { unscoped: true }),
  });
  return true;
}

/** Discard an interrupted prompt and open a fresh, empty new-task composer. */
export function discardPendingPrompt(key: string): void {
  pendingTaskPromptStoreApi.clear(key);
  openTaskInput();
}
