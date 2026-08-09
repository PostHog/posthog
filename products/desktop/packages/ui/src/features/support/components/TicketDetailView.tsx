import {
  ArrowLeftIcon,
  ChatCircleIcon,
  EnvelopeSimpleIcon,
  GlobeIcon,
  type Icon,
  LifebuoyIcon,
  MicrosoftTeamsLogoIcon,
  SlackLogoIcon,
} from "@phosphor-icons/react";
import type { Ticket, TicketMessage } from "@posthog/api-client/posthog-client";
import { classifyAttention } from "@posthog/core/support/attention";
import {
  Button,
  Empty,
  EmptyDescription,
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
  channelLabel,
  requesterEmail,
  requesterLabel,
  SLA_TEXT_CLASS,
  slaCountdownLabel,
  slaTone,
} from "../ticketPresentation";
import { AttentionChip } from "./AttentionChip";
import { ReplyComposer } from "./ReplyComposer";
import { TicketSidebar } from "./TicketSidebar";

const CHANNEL_ICONS: Record<string, Icon> = {
  email: EnvelopeSimpleIcon,
  slack: SlackLogoIcon,
  teams: MicrosoftTeamsLogoIcon,
  widget: ChatCircleIcon,
};

interface TicketDetailViewProps {
  ticketId: string;
}

/**
 * Thread on the left, context column on the right — the ticket's identity and
 * urgency stay pinned in the header while the conversation scrolls.
 */
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
          <EmptyMedia variant="icon">
            <LifebuoyIcon size={20} />
          </EmptyMedia>
          <EmptyTitle>Couldn't load this ticket</EmptyTitle>
          <EmptyDescription>
            It may have been deleted, or Conversations may be off for this
            project.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <TicketHeader ticket={ticket} now={now} />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {messages === undefined && (
              <div className="flex items-center justify-center py-8">
                <Spinner />
              </div>
            )}
            {messages?.map((message) => (
              <MessageItem key={message.id} message={message} />
            ))}
            {messages?.length === 0 && (
              <span className="text-[13px] text-muted-foreground">
                No messages on this ticket yet.
              </span>
            )}
          </div>
          <ReplyComposer ticketId={ticketId} />
        </div>
        <TicketSidebar ticket={ticket} messages={messages} />
      </div>
    </div>
  );
}

function TicketHeader({ ticket, now }: { ticket: Ticket; now: Date }) {
  const source =
    typeof ticket.channel_source === "string" ? ticket.channel_source : "";
  const ChannelIcon = CHANNEL_ICONS[source] ?? GlobeIcon;
  const label = requesterLabel(ticket);
  const email = requesterEmail(ticket);

  return (
    <div className="flex shrink-0 items-center gap-3 border-border border-b px-4 py-3">
      <Button
        type="button"
        aria-label="Back to Support"
        size="icon-sm"
        variant="outline"
        onClick={navigateToSupport}
      >
        <ArrowLeftIcon size={14} />
      </Button>
      <span className="shrink-0 font-medium font-mono text-[12px] text-muted-foreground">
        #{ticket.ticket_number}
      </span>
      <span
        role="img"
        className="shrink-0 text-muted-foreground"
        title={channelLabel(ticket.channel_source)}
        aria-label={channelLabel(ticket.channel_source)}
      >
        <ChannelIcon size={16} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-semibold text-[15px]">
          {ticket.email_subject || label}
        </span>
        <span className="truncate text-[11px] text-muted-foreground">
          {email && email !== label ? `${label} · ${email}` : label}
        </span>
      </div>
      <SlaChip ticket={ticket} now={now} />
      {/* The same reason chip the queue row showed, so opening a ticket
          doesn't lose the answer to "why was this at the top?". */}
      <AttentionChip state={classifyAttention(ticket, now)} ticket={ticket} />
    </div>
  );
}

/**
 * Countdown framed around the breach ("in 3h", "2h overdue") rather than a
 * clock time; the colour already says what the chip is.
 */
function SlaChip({ ticket, now }: { ticket: Ticket; now: Date }) {
  const tone = slaTone(ticket.sla_due_at, now);
  const countdown = slaCountdownLabel(ticket.sla_due_at, now);
  if (tone === "none" || !countdown) return null;
  const text = countdown.endsWith(" left")
    ? `in ${countdown.slice(0, -" left".length)}`
    : countdown;
  return (
    <span
      className={`shrink-0 rounded-full bg-muted px-2 py-0.5 font-medium text-[11px] ${SLA_TEXT_CLASS[tone]}`}
      title={
        ticket.sla_due_at
          ? `SLA due ${new Date(ticket.sla_due_at).toLocaleString()}`
          : undefined
      }
    >
      {text}
    </span>
  );
}

function MessageItem({ message }: { message: TicketMessage }) {
  return (
    <div
      className={`flex flex-col gap-1 rounded-md border px-3 py-2 ${
        message.is_private
          ? "border-warning bg-warning/40"
          : "border-border bg-card"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-[12px]">{message.author_name}</span>
        {message.is_private && (
          <span className="rounded-full bg-warning px-1.5 py-px font-medium text-[10px] text-warning-foreground">
            Internal
          </span>
        )}
        <RelativeTimestamp className="ml-auto" timestamp={message.created_at} />
      </div>
      {/* Plain text for now; rich_content (TipTap JSON) rendering is a
          follow-up once the queue exists. */}
      <span className="whitespace-pre-wrap text-[13px]">{message.content}</span>
    </div>
  );
}
