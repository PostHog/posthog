import { PaperPlaneTilt, Question } from "@phosphor-icons/react";
import type { SideChatThread } from "@posthog/core/sessions/sideChatService";
import {
  Button,
  ChatBubble,
  ChatBubbleContent,
  ChatMessage,
  ChatMessageContent,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Field,
  FieldLabel,
  Input,
  SkeletonText,
  Text,
} from "@posthog/quill";
import { ChatMarkdown } from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import { type FormEvent, useCallback } from "react";

export interface SideChatViewProps {
  taskId: string;
  thread: SideChatThread;
  question: string;
  onQuestionChange: (question: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

export function SideChatView({
  taskId,
  thread,
  question,
  onQuestionChange,
  onSubmit,
}: SideChatViewProps) {
  const scrollToLatest = useCallback((node: HTMLDivElement | null): void => {
    node?.scrollIntoView({ block: "end" });
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {thread.messages.length === 0 ? (
          <Empty className="h-full border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Question />
              </EmptyMedia>
              <EmptyTitle>Ask a side question</EmptyTitle>
              <EmptyDescription>
                Get an answer using the main chat as context. Side chat cannot
                edit files or change the main chat.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
            {thread.messages.map((message) => (
              <ChatMessage
                key={message.id}
                align={message.role === "user" ? "end" : "start"}
              >
                <ChatMessageContent>
                  <ChatBubble
                    variant={message.role === "user" ? "default" : "ghost"}
                  >
                    <ChatBubbleContent>
                      <ChatMarkdown content={message.content} />
                    </ChatBubbleContent>
                  </ChatBubble>
                </ChatMessageContent>
              </ChatMessage>
            ))}
            {thread.isLoading && (
              <ChatMessage align="start">
                <ChatMessageContent>
                  <ChatBubble variant="ghost">
                    <ChatBubbleContent className="w-64">
                      <SkeletonText lines={2} />
                    </ChatBubbleContent>
                  </ChatBubble>
                </ChatMessageContent>
              </ChatMessage>
            )}
            <div
              key={`${thread.messages.length}-${thread.isLoading}`}
              ref={scrollToLatest}
            />
          </div>
        )}
      </div>

      <form
        onSubmit={onSubmit}
        className="flex shrink-0 items-end gap-2 border-border border-t p-3"
      >
        <Field className="min-w-0 flex-1">
          <FieldLabel
            htmlFor={`side-chat-question-${taskId}`}
            className="sr-only"
          >
            Side chat question
          </FieldLabel>
          <Input
            id={`side-chat-question-${taskId}`}
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            placeholder="Ask without changing the main chat"
            autoComplete="off"
          />
          {thread.hasError && (
            <Text size="xs" variant="destructive">
              Couldn't answer this question. Try sending it again.
            </Text>
          )}
        </Field>
        <Button
          type="submit"
          variant="primary"
          size="icon"
          loading={thread.isLoading}
          disabled={!question.trim()}
          aria-label="Send side chat question"
          data-attr="side-chat-send"
        >
          <PaperPlaneTilt />
        </Button>
      </form>
    </div>
  );
}
