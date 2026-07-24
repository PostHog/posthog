import { openTaskInput } from "@posthog/ui/router/useOpenTask";
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
  pendingTaskPromptStoreApi.clear(newest.key);
  openTaskInput({ initialPrompt: newest.prompt.promptText });
}
