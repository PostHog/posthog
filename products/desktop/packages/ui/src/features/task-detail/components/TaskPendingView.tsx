import { ChatCircle } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { NEW_TASK_COMPOSER_FADE_MS } from "@posthog/ui/features/task-detail/newTaskComposerTransition";
import {
  discardPendingPrompt,
  recoverPendingPrompt,
} from "@posthog/ui/features/task-detail/pendingPromptActions";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { motion } from "framer-motion";
import { useCallback } from "react";
import {
  usePendingTaskPrompt,
  usePendingTaskPromptStore,
} from "../../../shell/pendingTaskPromptStore";
import { PendingChatView } from "../../sessions/components/PendingChatView";
import { InterruptedPromptView } from "./InterruptedPromptView";

interface TaskPendingViewProps {
  pendingTaskKey: string;
}

export function TaskPendingView({ pendingTaskKey }: TaskPendingViewProps) {
  const pending = usePendingTaskPrompt(pendingTaskKey);
  // The store persists through async host storage, so the first render always
  // sees an empty map. Without gating on hydration a reload straight onto this
  // route would flash "no longer available" over a record that is still on disk.
  const hasHydrated = usePendingTaskPromptStore((state) => state._hasHydrated);

  const handleRecover = useCallback(() => {
    recoverPendingPrompt(pendingTaskKey);
  }, [pendingTaskKey]);
  const handleDiscard = useCallback(() => {
    discardPendingPrompt(pendingTaskKey);
  }, [pendingTaskKey]);

  return (
    // Picks up where the new-task composer's fade-out left off, so submitting
    // reads as one phase handing over to the next.
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{
        duration: NEW_TASK_COMPOSER_FADE_MS / 1000,
        ease: "easeOut",
      }}
      className="relative h-full w-full bg-background"
    >
      {pending?.interruptReason ? (
        <InterruptedPromptView
          promptText={pending.promptText}
          attachments={pending.attachments}
          reason={pending.interruptReason}
          onRecover={handleRecover}
          onDiscard={handleDiscard}
        />
      ) : pending ? (
        <PendingChatView
          promptText={pending.promptText}
          attachments={pending.attachments}
        />
      ) : !hasHydrated ? (
        <div className="absolute inset-0 flex items-center justify-center p-6">
          <Spinner className="h-6 w-6" />
        </div>
      ) : (
        <div className="absolute inset-0 flex items-center justify-center p-6">
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ChatCircle />
              </EmptyMedia>
              <EmptyTitle>This prompt is no longer available</EmptyTitle>
              <EmptyDescription>
                It was already sent or discarded. Start a new task to keep
                going.
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button
                variant="primary"
                size="default"
                onClick={() => openTaskInput()}
              >
                Start a new task
              </Button>
            </EmptyContent>
          </Empty>
        </div>
      )}
    </motion.div>
  );
}
