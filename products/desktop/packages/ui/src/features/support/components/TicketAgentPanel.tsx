import { RobotIcon, SpinnerGapIcon } from "@phosphor-icons/react";
import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  InputGroup,
  InputGroupTextarea,
} from "@posthog/quill";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { useTicketAgentThread } from "@posthog/ui/features/support/hooks/useTicketAgentThread";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

const SUGGESTIONS = [
  "Summarize this ticket",
  "Is this possible in the product today?",
  "Investigate the cause",
];

export function TicketAgentPanel({
  ticket,
  messages,
}: {
  ticket: SupportTicket;
  messages: SupportTicketMessage[];
}) {
  const { taskId, startThread, isStarting } = useTicketAgentThread(ticket);

  if (taskId) {
    return <TicketAgentSession taskId={taskId} />;
  }

  return (
    <StartThreadForm
      isStarting={isStarting}
      onStart={(request) => void startThread(request, messages)}
    />
  );
}

function TicketAgentSession({ taskId }: { taskId: string }) {
  const { data: task, isError } = useQuery(taskDetailQuery(taskId));

  if (isError) {
    return (
      <Empty className="p-6">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <RobotIcon size={18} />
          </EmptyMedia>
          <EmptyTitle>This thread is unavailable</EmptyTitle>
          <EmptyDescription>
            The linked task could not be loaded.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <SpinnerGapIcon size={18} className="animate-spin text-gray-9" />
      </div>
    );
  }

  return <EmbeddedSessionView task={task} />;
}

function StartThreadForm({
  isStarting,
  onStart,
}: {
  isStarting: boolean;
  onStart: (request: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const canStart = draft.trim().length > 0 && !isStarting;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Empty className="flex-1 p-6">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <RobotIcon size={18} />
          </EmptyMedia>
          <EmptyTitle>Ask the agent about this ticket</EmptyTitle>
          <EmptyDescription>
            The first message starts a task seeded with the ticket and its
            conversation, shared with everyone who opens it.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          {SUGGESTIONS.map((suggestion) => (
            <Button
              key={suggestion}
              variant="outline"
              size="sm"
              disabled={isStarting}
              onClick={() => onStart(suggestion)}
            >
              {suggestion}
            </Button>
          ))}
        </EmptyContent>
      </Empty>

      <div className="flex shrink-0 flex-col gap-1 border-border border-t px-4 py-2">
        <InputGroup className="h-auto bg-card">
          <InputGroupTextarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask the agent…"
            className="max-h-[160px] min-h-[64px] resize-none text-[13px] [field-sizing:content]"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (canStart) {
                  onStart(draft.trim());
                }
              }
            }}
          />
        </InputGroup>
        <div className="flex items-center justify-end">
          <Button
            variant="primary"
            size="sm"
            disabled={!canStart}
            data-loading={isStarting || undefined}
            onClick={() => onStart(draft.trim())}
          >
            Start thread
          </Button>
        </div>
      </div>
    </div>
  );
}
