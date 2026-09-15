import type { SpendLimitCrossing } from "@posthog/core/billing/spendLimits";
import { spendStopMessage } from "@posthog/ui/features/billing/useSpendStop";

interface TaskComposerBlockers {
  spendStop: SpendLimitCrossing | null;
  /** What `useTaskCreation` itself refuses on, or null when it is willing. */
  creationBlockedReason: string | null;
  contextBlocked: boolean;
  workspaceModeResolved: boolean;
  configLoading: boolean;
  modelMissing: boolean;
}

/**
 * What the new-task composer's send button says while it refuses, or
 * undefined when nothing here holds the send. Without a reason the button
 * falls back to asking for a message, which is the wrong thing to tell
 * someone who has typed a prompt and only needs to pick a repository.
 */
export function taskComposerBlockedReason({
  spendStop,
  creationBlockedReason,
  contextBlocked,
  workspaceModeResolved,
  configLoading,
  modelMissing,
}: TaskComposerBlockers): string | undefined {
  if (spendStop) return spendStopMessage(spendStop);
  if (creationBlockedReason) return creationBlockedReason;
  if (contextBlocked) return "Waiting for space context";
  if (!workspaceModeResolved) return "Working out where to run this";
  if (configLoading) return "Getting things ready";
  if (modelMissing) return "Pick a model first";
  return undefined;
}
