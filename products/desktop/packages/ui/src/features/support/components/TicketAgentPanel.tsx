import { RobotIcon, SpinnerGapIcon } from "@phosphor-icons/react";
import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import { buildTicketAgentPrompt } from "@posthog/core/support/ticketTaskLink";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { ChannelHomeComposer } from "@posthog/ui/features/canvas/components/ChannelHomeComposer";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { useTicketAgentThread } from "@posthog/ui/features/support/hooks/useTicketAgentThread";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";

export function TicketAgentPanel({
  ticket,
  messages,
}: {
  ticket: SupportTicket;
  messages: SupportTicketMessage[];
}) {
  const { taskId, linkTask } = useTicketAgentThread(ticket);

  if (taskId) {
    return <TicketAgentSession taskId={taskId} />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col justify-end p-3">
      <ChannelHomeComposer
        contextKey={`ticket:${ticket.id}`}
        preferredWorkspaceMode="cloud"
        placeholder="Ask the agent about this ticket…"
        editorHeight="default"
        channelContext={buildTicketAgentPrompt(ticket, messages, "")}
        channelName={`Support ticket #${ticket.ticket_number}`}
        onTaskCreated={(task) => linkTask(task.id)}
      />
    </div>
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
