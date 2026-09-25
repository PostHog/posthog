import { hasAgentMention } from "@posthog/core/canvas/threadTimeline";
import { Checkbox, Label } from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { CommentComposer } from "@posthog/ui/features/sessions/components/CommentComposer";
import { computeCommentActionPlacement } from "@posthog/ui/features/sessions/components/selectionCommentAction";
import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";

const CARD_SIZE = { width: 360, height: 190 };

export function PreviewCommentCard({
  anchor,
  elementLabel,
  members,
  onSubmit,
  onDismiss,
}: {
  anchor: { top: number; right: number; bottom: number };
  elementLabel: string;
  members: UserBasic[];
  onSubmit: (
    content: string,
    mentions: number[],
    sendToAgent: boolean,
  ) => Promise<void>;
  onDismiss: () => void;
}) {
  const checkboxId = useId();
  const [draft, setDraft] = useState("");
  const [checked, setChecked] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const sendToAgent = checked || hasAgentMention(draft);
  const position = computeCommentActionPlacement(
    anchor,
    { width: window.innerWidth, height: window.innerHeight },
    CARD_SIZE,
    "below",
  );

  useEffect(() => {
    const dismissOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Element &&
        event.target.closest("[data-preview-comment-card]")
      ) {
        return;
      }
      onDismiss();
    };
    document.addEventListener("pointerdown", dismissOutside, true);
    return () =>
      document.removeEventListener("pointerdown", dismissOutside, true);
  }, [onDismiss]);

  return createPortal(
    <div
      data-preview-comment-card=""
      className="fixed z-50 flex w-[360px] max-w-[80vw] flex-col gap-2 rounded-md border border-border bg-background p-2 shadow-lg"
      style={position}
    >
      <span className="truncate text-muted-foreground text-xs">
        {elementLabel}
      </span>
      <CommentComposer
        value={draft}
        onValueChange={setDraft}
        onSubmit={async (content, mentions) => {
          if (submitting) return;
          setSubmitting(true);
          try {
            await onSubmit(content, mentions, sendToAgent);
            onDismiss();
          } finally {
            setSubmitting(false);
          }
        }}
        onCancel={onDismiss}
        members={members}
        placeholder="Add a comment. Mention @agent to ask the agent."
        rows={2}
        disabled={submitting}
        autoFocus
      />
      <Label
        htmlFor={checkboxId}
        className="flex cursor-pointer items-center gap-2 text-xs"
      >
        <Checkbox
          id={checkboxId}
          checked={sendToAgent}
          data-attr="task-preview-comment-send-to-agent"
          onCheckedChange={(value) => setChecked(value === true)}
        />
        Send to agent
      </Label>
    </div>,
    document.body,
  );
}
