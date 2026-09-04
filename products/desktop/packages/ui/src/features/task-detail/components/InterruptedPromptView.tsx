import type { PendingPromptInterruptReason } from "@posthog/core/tasks/pendingPrompts";
import { Button, Text } from "@posthog/quill";
import { UserMessage } from "@posthog/ui/features/sessions/components/session-update/UserMessage";
import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";

interface InterruptedPromptViewProps {
  promptText: string;
  attachments?: UserMessageAttachment[];
  reason: PendingPromptInterruptReason;
  onRecover: () => void;
  onDiscard: () => void;
}

const STATUS: Record<
  PendingPromptInterruptReason,
  { title: string; detail: string }
> = {
  offline: {
    title: "You're offline, so this task hasn't started",
    detail:
      "Your prompt is saved. Recover it to try again once you're back online.",
  },
  failed: {
    title: "This task couldn't start",
    detail: "Your prompt is saved. Recover it to edit and try again.",
  },
};

/**
 * Shown on the pending route when task setup failed and left the prompt unsent.
 * Keeps the prompt on screen with actions to recover it into the composer or
 * discard it, instead of dropping the user onto an empty screen.
 */
export function InterruptedPromptView({
  promptText,
  attachments,
  reason,
  onRecover,
  onDiscard,
}: InterruptedPromptViewProps) {
  const status = STATUS[reason];
  return (
    <div className="absolute inset-0 flex flex-col bg-background">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div
          className="mx-auto flex flex-col gap-3 px-2 py-1.5"
          style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
        >
          <UserMessage
            content={promptText}
            attachments={attachments}
            animate={false}
          />
        </div>
      </div>
      <div
        className="mx-auto w-full p-2"
        style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
      >
        <div className="flex flex-col gap-3 rounded-(--radius-3) border border-(--gray-5) bg-(--gray-2) p-4">
          <div className="flex flex-col gap-1">
            <Text weight="medium" className="text-(--gray-12)">
              {status.title}
            </Text>
            <Text size="sm" className="text-(--gray-11)">
              {status.detail}
            </Text>
          </div>
          <div className="flex gap-2">
            <Button variant="primary" size="default" onClick={onRecover}>
              Recover prompt
            </Button>
            <Button variant="outline" size="default" onClick={onDiscard}>
              Discard
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
