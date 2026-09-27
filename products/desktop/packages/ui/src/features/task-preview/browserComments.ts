import type {
  CommentAnchor,
  CommentTarget,
} from "@posthog/core/comments/anchors";

export function browserCommentTarget(taskId: string): CommentTarget {
  return { scope: "task_browser", itemId: `${taskId}:browser` };
}

export function browserCommentPage(
  anchor: CommentAnchor | null | undefined,
): { url: string; label: string } | null {
  if (anchor?.kind !== "element" || !anchor.origin) return null;
  try {
    const url = new URL(anchor.path, anchor.origin);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    const path = url.pathname === "/" ? "" : url.pathname;
    return { url: url.toString(), label: `${url.host}${path}` };
  } catch {
    return null;
  }
}
