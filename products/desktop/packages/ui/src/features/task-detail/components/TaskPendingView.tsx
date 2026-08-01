import { Box } from "@radix-ui/themes";
import { usePendingTaskPrompt } from "../../../shell/pendingTaskPromptStore";
import { PendingChatView } from "../../sessions/components/PendingChatView";

interface TaskPendingViewProps {
  pendingTaskKey: string;
}

export function TaskPendingView({ pendingTaskKey }: TaskPendingViewProps) {
  const pending = usePendingTaskPrompt(pendingTaskKey);

  return (
    <Box className="relative h-full w-full bg-background">
      <PendingChatView
        promptText={pending?.promptText ?? ""}
        attachments={pending?.attachments}
      />
    </Box>
  );
}
