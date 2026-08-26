import { PushPinIcon } from "@phosphor-icons/react";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { ticketSlaState } from "@posthog/core/support/ticketState";
import { readTicketTaskId } from "@posthog/core/support/ticketTaskLink";
import { Badge, cn, Text } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import {
  formatSlaCountdown,
  SLA_TEXT_CLASSES,
  TICKET_PRIORITY_VARIANTS,
  TICKET_STATUS_VARIANTS,
  ticketPriorityLabel,
  ticketRequesterName,
  ticketStatusLabel,
} from "@posthog/ui/features/support/ticketPresentation";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";

export function TicketRow({
  ticket,
  isActive,
  isPinned,
  now,
  onSelect,
}: {
  ticket: SupportTicket;
  isActive: boolean;
  isPinned: boolean;
  now: number;
  onSelect: () => void;
}) {
  const sla = ticketSlaState(ticket, now);
  const lastActivityAt = ticket.last_message_at ?? ticket.updated_at;

  return (
    <button
      type="button"
      onClick={onSelect}
      data-active={isActive || undefined}
      className="flex w-full cursor-default flex-col gap-1 rounded-(--radius-2) px-2 py-1.5 text-left transition-colors hover:bg-fill-hover data-active:bg-fill-selected"
    >
      <div className="flex min-w-0 items-center gap-1.5">
        {isPinned && (
          <PushPinIcon
            size={11}
            weight="fill"
            className="shrink-0 text-(--accent-11)"
          />
        )}
        <Text className="min-w-0 flex-1 truncate font-medium text-[13px]">
          {ticketRequesterName(ticket)}
        </Text>
        <CountBadge count={ticket.unread_team_count ?? 0} />
        <Text
          className="shrink-0 text-[11px] text-gray-11 tabular-nums"
          title={new Date(lastActivityAt).toLocaleString()}
        >
          {formatRelativeTimeShort(lastActivityAt)}
        </Text>
      </div>

      <Text className="truncate text-[12px] text-muted-foreground leading-snug">
        {ticket.last_message_text || `#${ticket.ticket_number}`}
      </Text>

      <div className="flex min-w-0 items-center gap-1.5">
        <Badge variant={TICKET_STATUS_VARIANTS[ticket.status ?? "new"]}>
          {ticketStatusLabel(ticket.status)}
        </Badge>
        {ticket.priority && (
          <Badge variant={TICKET_PRIORITY_VARIANTS[ticket.priority]}>
            {ticketPriorityLabel(ticket.priority)}
          </Badge>
        )}
        {readTicketTaskId(ticket.tags) && (
          <Badge variant="default">Agent</Badge>
        )}
        {(sla === "at-risk" || sla === "breached") && (
          <Text
            className={cn(
              "ml-auto shrink-0 text-[11px] tabular-nums",
              SLA_TEXT_CLASSES[sla],
            )}
          >
            {formatSlaCountdown(ticket.sla_due_at, now)}
          </Text>
        )}
      </div>
    </button>
  );
}
