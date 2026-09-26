import type { CommentTarget } from "@posthog/core/comments/anchors";

export function previewCommentTarget(
  taskId: string,
  port: number,
): CommentTarget {
  return { scope: "task_preview", itemId: `${taskId}:${port}` };
}
