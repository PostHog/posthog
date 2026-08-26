import { NEW_TASK_COMPOSER_FADE_MS } from "@posthog/ui/features/task-detail/newTaskComposerTransition";
import { motion } from "framer-motion";
import { usePendingTaskPrompt } from "../../../shell/pendingTaskPromptStore";
import { PendingChatView } from "../../sessions/components/PendingChatView";

interface TaskPendingViewProps {
  pendingTaskKey: string;
}

export function TaskPendingView({ pendingTaskKey }: TaskPendingViewProps) {
  const pending = usePendingTaskPrompt(pendingTaskKey);

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
      <PendingChatView
        promptText={pending?.promptText ?? ""}
        attachments={pending?.attachments}
      />
    </motion.div>
  );
}
