import type { ElementCommentAnchor } from "@posthog/core/comments/anchors";
import {
  type EditorContent,
  isContentEmpty,
} from "@posthog/core/message-editor/content";

const AGENT_MENTION = /(^|\s)@agent\b/gi;

export function previewCommentPrompt({
  port,
  anchor,
  comment,
}: {
  port: number;
  anchor: ElementCommentAnchor;
  comment: string;
}): string {
  const request = comment
    .replace(AGENT_MENTION, "$1")
    .replace(/\s+/g, " ")
    .trim();
  const label = anchor.text ? ` "${anchor.text}"` : "";
  return [
    `On the preview page http://localhost:${port}${anchor.path}, change the <${anchor.tag}> element${label} at selector \`${anchor.selector}\`:`,
    request,
    "",
    "Element HTML:",
    "```html",
    anchor.html,
    "```",
  ].join("\n");
}

export function previewCommentComposerContent({
  port,
  anchor,
  comment,
  currentDraft,
}: {
  port: number;
  anchor: ElementCommentAnchor;
  comment: string;
  currentDraft: EditorContent | string | null;
}): EditorContent {
  const prompt = previewCommentPrompt({ port, anchor, comment });
  return {
    segments: [
      {
        type: "text",
        text: isContentEmpty(currentDraft) ? prompt : `\n\n${prompt}`,
      },
    ],
  };
}
