import { ChatCircleIcon, RobotIcon } from "@phosphor-icons/react";
import type { SupportTicketMessage } from "@posthog/api-client/posthog-client";
import {
  Badge,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Text,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ChatMarkdown } from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import { messageAuthorLabel } from "@posthog/ui/features/support/ticketPresentation";
import { useEffect, useRef } from "react";

export function TicketThread({
  messages,
}: {
  messages: SupportTicketMessage[];
}) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const lastMessageId = messages.at(-1)?.id;

  useEffect(() => {
    if (!lastMessageId) {
      return;
    }
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [lastMessageId]);

  if (messages.length === 0) {
    return (
      <Empty className="p-6">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ChatCircleIcon size={18} />
          </EmptyMedia>
          <EmptyTitle>No messages yet</EmptyTitle>
          <EmptyDescription>
            This ticket has no conversation on it.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
      <div className="flex flex-col gap-3">
        {messages.map((message) => (
          <TicketMessageRow key={message.id} message={message} />
        ))}
      </div>
      <div ref={bottomRef} />
    </div>
  );
}

function TicketMessageRow({ message }: { message: SupportTicketMessage }) {
  const fromCustomer = message.author_type !== "support";
  const isNote = message.is_private;
  const fromUs = !fromCustomer && !isNote;

  return (
    <div className={cn("flex", fromUs ? "justify-end" : "justify-start")}>
      <div className="flex min-w-0 max-w-[85%] flex-col gap-1">
        <div
          className={cn(
            "flex items-baseline gap-2 px-1",
            fromUs && "flex-row-reverse",
          )}
        >
          <Text className="font-medium text-[12px]">
            {messageAuthorLabel(message)}
          </Text>
          {message.author_type === "AI" && (
            <Badge variant="default">
              <RobotIcon size={10} />
              AI
            </Badge>
          )}
          <Text className="shrink-0 text-[11px] text-gray-11 tabular-nums">
            {formatRelativeTimeShort(message.created_at)}
          </Text>
        </div>

        <div
          className={cn(
            "rounded-(--radius-3) border px-3 py-2",
            isNote && "border-warning/40 bg-warning/10",
            fromUs && !isNote && "border-transparent bg-fill-selected",
            fromCustomer && !isNote && "border-border bg-card",
          )}
        >
          {isNote && (
            <Text className="mb-1 block font-semibold text-[10px] text-warning-foreground uppercase tracking-wide">
              Internal note
            </Text>
          )}
          <div className="min-w-0 break-words text-[13px]">
            <ChatMarkdown content={message.content} />
          </div>
          {message.version > 0 && (
            <Text className="mt-1 block text-[10px] text-muted-foreground">
              Edited
            </Text>
          )}
        </div>
      </div>
    </div>
  );
}
