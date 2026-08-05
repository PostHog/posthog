import { Button, Switch, Textarea } from "@posthog/quill";
import { toast } from "@posthog/ui/primitives/toast";
import { useState } from "react";
import { useSupportTicketReply } from "../hooks/useSupportTicketReply";

// Server-enforced cap on TicketReplyRequestSerializer.message.
const REPLY_MAX_LENGTH = 5000;

/**
 * Human-typed replies only. With the internal-note switch off, the server
 * delivers the message to the customer over the ticket's channel; on, it
 * stays team-only. AI drafting is explicitly out of scope (plan non-goals).
 */
export function ReplyComposer({ ticketId }: { ticketId: string }) {
  const [message, setMessage] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const reply = useSupportTicketReply(ticketId);

  const send = () => {
    const trimmed = message.trim();
    if (!trimmed || reply.isPending) return;
    reply.mutate(
      { message: trimmed, isPrivate },
      {
        onSuccess: () => setMessage(""),
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <div className="shrink-0 border-(--gray-4) border-t px-4 py-3">
      <Textarea
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            send();
          }
        }}
        maxLength={REPLY_MAX_LENGTH}
        rows={3}
        placeholder={
          isPrivate
            ? "Add an internal note (only your team sees this)"
            : "Reply to the customer…"
        }
      />
      <div className="mt-2 flex items-center gap-2">
        <Switch
          id="support-reply-internal"
          checked={isPrivate}
          onCheckedChange={(checked: boolean) => setIsPrivate(checked)}
        />
        <label
          htmlFor="support-reply-internal"
          className="cursor-pointer text-(--gray-11) text-[12px]"
        >
          Internal note
        </label>
        <Button
          type="button"
          variant="primary"
          size="sm"
          className="ml-auto"
          loading={reply.isPending}
          disabled={!message.trim()}
          onClick={send}
        >
          {isPrivate ? "Add note" : "Send reply"}
        </Button>
      </div>
    </div>
  );
}
