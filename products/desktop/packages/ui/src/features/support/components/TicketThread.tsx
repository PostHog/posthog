import { ChatCircleIcon, RobotIcon } from "@phosphor-icons/react";
import type { SupportTicketMessage } from "@posthog/api-client/posthog-client";
import {
  Badge,
  ChatBubble,
  ChatBubbleContent,
  ChatMessage,
  ChatMessageContent,
  ChatMessageFooter,
  ChatMessageHeader,
  ChatMessageScroller,
  ChatMessageScrollerButton,
  ChatMessageScrollerContent,
  ChatMessageScrollerItem,
  ChatMessageScrollerProvider,
  ChatMessageScrollerViewport,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Text,
} from "@posthog/quill";
import { ChatMarkdown } from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import { messageAuthorLabel } from "@posthog/ui/features/support/ticketPresentation";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";

export function TicketThread({
  messages,
}: {
  messages: SupportTicketMessage[];
}) {
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
    <ChatMessageScrollerProvider>
      <ChatMessageScroller className="min-h-0 flex-1">
        <ChatMessageScrollerViewport>
          <ChatMessageScrollerContent density="dense" className="px-4 py-3">
            {messages.map((message) => (
              <ChatMessageScrollerItem key={message.id} messageId={message.id}>
                <TicketMessageRow message={message} />
              </ChatMessageScrollerItem>
            ))}
          </ChatMessageScrollerContent>
        </ChatMessageScrollerViewport>
        <ChatMessageScrollerButton />
      </ChatMessageScroller>
    </ChatMessageScrollerProvider>
  );
}

function TicketMessageRow({ message }: { message: SupportTicketMessage }) {
  const isNote = message.is_private;
  const fromUs =
    message.author_type === "support" || message.author_type === "AI";
  const align = fromUs ? "end" : "start";

  return (
    <ChatMessage align={align}>
      <ChatMessageContent>
        <ChatMessageHeader className="gap-1.5">
          <Text className="font-medium text-[12px]">
            {messageAuthorLabel(message)}
          </Text>
          {message.author_type === "AI" && (
            <Badge variant="default">
              <RobotIcon size={10} />
              AI
            </Badge>
          )}
          <RelativeTimestamp
            timestamp={message.created_at}
            className="text-gray-11 tabular-nums"
          />
        </ChatMessageHeader>

        <ChatBubble
          align={align}
          variant="outline"
          className={cn(
            "bg-card",
            isNote && "border-(--amber-6) bg-(--amber-3)",
          )}
        >
          <ChatBubbleContent>
            {isNote && (
              <Text className="mb-1 block font-semibold text-(--amber-11) text-[10px] uppercase tracking-wide">
                Internal note
              </Text>
            )}
            <div className="min-w-0 break-words text-[13px]">
              <ChatMarkdown content={message.content} />
            </div>
          </ChatBubbleContent>
        </ChatBubble>

        {message.version > 0 && (
          <ChatMessageFooter>
            <Text className="text-[10px] text-muted-foreground">Edited</Text>
          </ChatMessageFooter>
        )}
      </ChatMessageContent>
    </ChatMessage>
  );
}
