import { recoverPendingPrompt } from "@posthog/ui/features/task-detail/pendingPromptActions";
import { logger } from "@posthog/ui/shell/logger";
import { pendingTaskPromptStoreApi } from "@posthog/ui/shell/pendingTaskPromptStore";
import { useEffect } from "react";

const log = logger.scope("pending-prompt-recovery");

let recoveryStarted = false;

export function PendingPromptRecovery(): null {
  useEffect(() => {
    if (recoveryStarted) {
      return;
    }
    recoveryStarted = true;
    void recoverNewestPendingPrompt();
  }, []);
  return null;
}

async function recoverNewestPendingPrompt(): Promise<void> {
  await pendingTaskPromptStoreApi.whenHydrated();
  const orphans = pendingTaskPromptStoreApi.getAllNewestFirst();
  const [newest] = orphans;
  if (!newest) {
    return;
  }

  log.info("Recovering an unsent prompt whose task never finished creating", {
    remaining: orphans.length - 1,
  });
  // Restore the full content into the composer before clearing the record, so a
  // crash mid-recovery can't lose the prompt. Older orphans stay put and surface
  // on later launches.
  recoverPendingPrompt(newest.key);
}
