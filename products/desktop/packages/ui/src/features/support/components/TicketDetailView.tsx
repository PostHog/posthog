import { ArrowLeftIcon } from "@phosphor-icons/react";
import type { TicketMessage } from "@posthog/api-client/posthog-client";
import {
  Badge,
  Button,
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { navigateToSupport } from "@posthog/ui/router/navigationBridge";
import { useMemo } from "react";
import { useSupportTicket } from "../hooks/useSupportTicket";
import { useSupportTicketMessages } from "../hooks/useSupportTicketMessages";
import {
  assigneeDisplay,
  channelLabel,
  requesterLabel,
  slaState,
} from "../ticketPresentation";
import { ReplyComposer } from "./ReplyComposer";
import { TicketActions } from "./TicketActions";

interface TicketDetailViewProps {
  ticketId: string;
}

export function TicketDetailView({ ticketId }: TicketDetailViewProps) {
  const { data: ticket, isPending, isError } = useSupportTicket(ticketId);
  const { data: messages } = useSupportTicketMessages(ticketId);
  const now = useMemo(() => new Date(), []);

  if (isPending) {
    return (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Spinner />
          </EmptyMedia>
          <EmptyTitle>Loading ticket</EmptyTitle>
        </EmptyHeader>
      </Empty>
    );
  }

  if (isError || !ticket) {
    return (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyTitle>Couldn't load this ticket</EmptyTitle>
        </EmptyHeader>
      </Empty>
    );
  }

  const assignee = assigneeDisplay(ticket.assignee);
  const sla = slaState(ticket.sla_due_at, now);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-col gap-2 border-(--gray-4) border-b px-4 pt-3 pb-3">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            aria-label="Back to Support"
            size="icon-sm"
            onClick={navigateToSupport}
          >
            <ArrowLeftIcon size={14} />
          </Button>
          <h3 className="min-w-0 truncate font-semibold text-[15px]">
            {ticket.email_subject || requesterLabel(ticket)}
          </h3>
          <span className="shrink-0 text-(--gray-9) text-[12px]">
            #{ticket.ticket_number}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <TicketActions ticket={ticket} />
          {sla.kind === "breached" && (
            <Badge variant="destructive">SLA breached</Badge>
          )}
          {sla.kind === "due" && (
            <Badge variant="warning">
              SLA <RelativeTimestamp timestamp={sla.dueAt} />
            </Badge>
          )}
          <span className="text-(--gray-10) text-[12px]">
            {channelLabel(ticket.channel_source)}
          </span>
          <span className="text-(--gray-10) text-[12px]">
            {assignee.kind === "role"
              ? `${assignee.label} (pool)`
              : assignee.label}
          </span>
          <span className="text-(--gray-10) text-[12px]">
            From {requesterLabel(ticket)}
          </span>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {messages === undefined && (
          <div className="flex items-center justify-center py-8">
            <Spinner />
          </div>
        )}
        {messages?.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
        {messages?.length === 0 && (
          <span className="text-(--gray-10) text-[13px]">
            No messages on this ticket yet.
          </span>
        )}
      </div>
      <ReplyComposer ticketId={ticketId} />
    </div>
  );
}

function MessageItem({ message }: { message: TicketMessage }) {
  return (
    <div
      className={`flex flex-col gap-1 rounded-md px-2 py-2 ${
        message.is_private ? "bg-(--amber-2)" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-[12px]">{message.author_name}</span>
        {message.is_private && <Badge variant="warning">Internal</Badge>}
        <RelativeTimestamp timestamp={message.created_at} />
      </div>
      {/* Plain text for now; rich_content (TipTap JSON) rendering is a
          follow-up once the queue exists. */}
      <span className="whitespace-pre-wrap text-[13px]">
        {message.content}
      </span>
    </div>
  );
}
