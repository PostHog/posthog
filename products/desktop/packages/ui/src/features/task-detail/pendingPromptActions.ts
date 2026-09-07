import { pendingPromptToContent } from "@posthog/core/tasks/pendingPrompts";
import {
  isBrowserTabOpen,
  navigateBrowserTab,
} from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { pendingTaskPromptStoreApi } from "@posthog/ui/shell/pendingTaskPromptStore";

/**
 * Drop a failed or interrupted prompt back into the new-task composer. The
 * durable record is kept and handed to the composer as `recoveredFromKey`; the
 * composer clears it only once it has applied the content (see TaskInput). So a
 * crash before the composer mounts leaves the record intact for the next launch
 * to recover, never a cleared record whose content lived only in memory.
 * Returns false when the record is already gone (nothing to recover).
 *
 * `originTabId` routes the recovery to the tab that submitted the prompt.
 * Without it the composer opens in whichever tab is currently active, which can
 * be a tab the submitter never looked at.
 */
export function recoverPendingPrompt(
  key: string,
  originTabId?: string | null,
): boolean {
  const record = pendingTaskPromptStoreApi.get(key);
  if (!record) return false;
  const options = {
    initialContent: pendingPromptToContent(record),
    recoveredFromKey: key,
    // Reopen in the space the prompt was submitted in, not whatever is current.
    ...(record.channelId
      ? { channelId: record.channelId }
      : { unscoped: true }),
  };
  // The active tab navigates now; a background tab stores the composer as its
  // durable target and picks up the prefill when the user returns to it; a
  // closed tab does nothing and the record stays for next-launch recovery.
  navigateBrowserTab(
    originTabId ?? null,
    {
      href: record.channelId ? `/spaces/${record.channelId}/new` : "/new",
      title: "New task",
      channelId: record.channelId ?? null,
    },
    () => openTaskInput(options),
  );
  return true;
}

/**
 * Settle the pending-prompt record after a failed task creation.
 *
 * With a task id, onTaskReady already navigated the origin tab onto the
 * rolled-back task, so recovery sends that tab back to the composer with the
 * prompt. Without one the origin composer still holds the draft, so the record
 * would only duplicate it at the next launch and is cleared — unless the tab
 * is gone, because closing a tab clears its draft and the record is then the
 * only surviving copy. Kept records surface again through
 * PendingPromptRecovery on the next launch.
 */
export function settleFailedPromptRecord(args: {
  recordKey: string | null;
  createdTaskId?: string;
  originTabId: string | null;
}): void {
  const { recordKey, createdTaskId, originTabId } = args;
  if (!recordKey) return;
  if (createdTaskId) {
    recoverPendingPrompt(createdTaskId, originTabId);
    return;
  }
  if (isBrowserTabOpen(originTabId)) {
    pendingTaskPromptStoreApi.clear(recordKey);
  }
}
