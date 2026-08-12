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
  ThreadItem,
  ThreadItemAuthor,
  ThreadItemBody,
  ThreadItemContent,
  ThreadItemGroup,
  ThreadItemHeader,
} from "@posthog/quill";
import {
  formatTicketAge,
  isTeamAuthoredMessage,
  messageAuthorLabel,
} from "@posthog/ui/features/support/ticketPresentation";
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

  const now = Date.now();

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
      <ThreadItemGroup>
        {messages.map((message) => (
          <TicketMessageRow key={message.id} message={message} now={now} />
        ))}
      </ThreadItemGroup>
      <div ref={bottomRef} />
    </div>
  );
}

function TicketMessageRow({
  message,
  now,
}: {
  message: SupportTicketMessage;
  now: number;
}) {
  const fromTeam = isTeamAuthoredMessage(message);

  return (
    <ThreadItem>
      <ThreadItemContent>
        <ThreadItemHeader>
          <ThreadItemAuthor className="text-[13px]">
            {messageAuthorLabel(message)}
          </ThreadItemAuthor>
          {message.author_type === "AI" && (
            <Badge variant="default">
              <RobotIcon size={10} />
              AI
            </Badge>
          )}
          {message.is_private && <Badge variant="warning">Internal note</Badge>}
          {!fromTeam && !message.is_private && (
            <Badge variant="info">Customer</Badge>
          )}
          <Text className="ml-auto shrink-0 text-[11px] text-gray-11 tabular-nums">
            {formatTicketAge(message.created_at, now)}
          </Text>
        </ThreadItemHeader>
        <ThreadItemBody
          className={cn(
            "mt-1.5 whitespace-pre-wrap break-words text-[13px]",
            message.is_private && "text-warning-foreground",
          )}
        >
          {message.content}
        </ThreadItemBody>
        {message.version > 0 && (
          <Text className="text-[10px] text-muted-foreground">Edited</Text>
        )}
      </ThreadItemContent>
    </ThreadItem>
  );
}
