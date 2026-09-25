import type { ElementCommentAnchor } from "@posthog/core/comments/anchors";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { showTaskChat } from "@posthog/ui/features/sessions/showTaskChat";
import { previewCommentComposerContent } from "./previewAgentContent";

export function attachPreviewCommentToComposer({
  taskId,
  port,
  anchor,
  comment,
}: {
  taskId: string;
  port: number;
  anchor: ElementCommentAnchor;
  comment: string;
}): void {
  const actions = useDraftStore.getState().actions;
  actions.insertPendingContent(
    taskId,
    previewCommentComposerContent({
      port,
      anchor,
      comment,
      currentDraft: actions.getDraft(taskId),
    }),
  );
  showTaskChat(taskId);
  actions.requestFocus(taskId);
}
