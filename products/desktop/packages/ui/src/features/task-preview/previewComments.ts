import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type { ElementCommentAnchor } from "@posthog/core/comments/anchors";
import {
  type CommentEntry,
  resourceEntry,
} from "@posthog/ui/features/canvas/components/taskCommentThreads";
import {
  buildCommentThreads,
  readCommentContext,
} from "@posthog/ui/features/sessions/components/commentViewTypes";
import type { TaskPreviewPin } from "./taskPreviewFrameHost";

export type PreviewThread = {
  id: string;
  number: number;
  root: ResourceComment;
  anchor: ElementCommentAnchor;
  entries: CommentEntry[];
  resolved: boolean;
};

export function previewPathname(path: string): string {
  try {
    return new URL(path, "http://preview.invalid").pathname;
  } catch {
    return "/";
  }
}

export function previewThreads(comments: ResourceComment[]): PreviewThread[] {
  return buildCommentThreads(comments)
    .flatMap((thread) => {
      const anchor = readCommentContext(thread.root)?.anchor;
      if (anchor?.kind !== "element") return [];
      const visibleReplies = thread.replies.filter(
        (reply) => !readCommentContext(reply)?.threadState,
      );
      return [
        {
          id: thread.root.id,
          root: thread.root,
          anchor,
          entries: [thread.root, ...visibleReplies].map(resourceEntry),
          resolved: thread.resolved,
        },
      ];
    })
    .sort((a, b) => a.root.created_at.localeCompare(b.root.created_at))
    .map((thread, index) => ({ ...thread, number: index + 1 }));
}

export function previewPins(
  threads: PreviewThread[],
  activeThreadId: string | null,
): TaskPreviewPin[] {
  return threads
    .filter((thread) => !thread.resolved)
    .map((thread) => ({
      id: thread.id,
      number: thread.number,
      path: previewPathname(thread.anchor.path),
      selector: thread.anchor.selector,
      active: thread.id === activeThreadId,
    }));
}
