import { RobotIcon } from "@phosphor-icons/react";
import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import { ticketAgentThreadNeverStarted } from "@posthog/core/support/ticketAgentSession";
import { buildTicketAgentPrompt } from "@posthog/core/support/ticketTaskLink";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import {
  ChannelHomeComposer,
  type ChannelHomeComposerHandle,
} from "@posthog/ui/features/canvas/components/ChannelHomeComposer";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { useSessionForTask } from "@posthog/ui/features/sessions/sessionStore";
import { useTicketAgentThread } from "@posthog/ui/features/support/hooks/useTicketAgentThread";
import { TICKET_AGENT_SUGGESTIONS } from "@posthog/ui/features/support/ticketAgentSuggestions";
import { SuggestedPromptCard } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import {
  useWorkspace,
  useWorkspaceLoaded,
} from "@posthog/ui/features/workspace/useWorkspace";
import { navigateToTaskDetail } from "@posthog/ui/router/navigationBridge";
import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";

export function TicketAgentPanel({
  ticket,
  messages,
}: {
  ticket: SupportTicket;
  messages: SupportTicketMessage[];
}) {
  const { taskId, linkTask, unlinkTask } = useTicketAgentThread(ticket);
  const composerRef = useRef<ChannelHomeComposerHandle>(null);

  if (taskId) {
    return <TicketAgentSession taskId={taskId} onUnlink={unlinkTask} />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col justify-end gap-3 p-3">
      <div className="min-h-0 overflow-y-auto px-0.5 pb-1">
        <Text className="mb-1.5 block px-0.5 font-medium text-[11px] text-muted-foreground">
          Suggestions
        </Text>
        <div className="flex flex-col gap-1.5">
          {TICKET_AGENT_SUGGESTIONS.map((suggestion) => (
            <SuggestedPromptCard
              key={suggestion.label}
              suggestion={suggestion}
              onSelect={() =>
                composerRef.current?.applySuggestion(
                  suggestion.prompt,
                  suggestion.mode,
                )
              }
            />
          ))}
        </div>
      </div>
      <ChannelHomeComposer
        ref={composerRef}
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

function TicketAgentSession({
  taskId,
  onUnlink,
}: {
  taskId: string;
  onUnlink: () => void;
}) {
  const { data: task, isError } = useQuery(taskDetailQuery(taskId));
  const session = useSessionForTask(taskId);
  const workspace = useWorkspace(taskId);
  const workspaceLoaded = useWorkspaceLoaded();

  if (isError) {
    return (
      <AgentPanelEmpty
        title="This chat is no longer available"
        description="The linked task was deleted or belongs to another project."
        onUnlink={onUnlink}
      />
    );
  }

  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-4 text-gray-9" />
      </div>
    );
  }

  const neverStarted = ticketAgentThreadNeverStarted({
    workspaceLoaded,
    hasRun: !!task.latest_run?.id,
    hasWorkspace: !!workspace,
    hasSession: !!session,
  });

  if (neverStarted) {
    return (
      <AgentPanelEmpty
        title="This chat never started"
        description="The task was created but no agent run began."
        onUnlink={onUnlink}
        onOpenTask={() => navigateToTaskDetail(taskId)}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-border border-b px-3 py-1.5">
        <Text className="min-w-0 truncate text-[12px] text-muted-foreground">
          {task.title}
        </Text>
        <Button variant="outline" size="sm" onClick={onUnlink}>
          Unlink
        </Button>
      </div>
      <div className="min-h-0 flex-1">
        <EmbeddedSessionView task={task} />
      </div>
    </div>
  );
}

function AgentPanelEmpty({
  title,
  description,
  onUnlink,
  onOpenTask,
}: {
  title: string;
  description: string;
  onUnlink: () => void;
  onOpenTask?: () => void;
}) {
  return (
    <Empty className="p-6">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <RobotIcon size={18} />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {onOpenTask && (
          <Button variant="outline" size="sm" onClick={onOpenTask}>
            Open task
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={onUnlink}>
          Unlink and start again
        </Button>
      </EmptyContent>
    </Empty>
  );
}
