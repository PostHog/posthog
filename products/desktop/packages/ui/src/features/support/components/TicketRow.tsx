import { GitPullRequestIcon } from "@phosphor-icons/react";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { readTicketPrUrls } from "@posthog/core/support/ticketPrLinks";
import {
  ticketAttention,
  ticketSlaState,
} from "@posthog/core/support/ticketState";
import { readTicketTaskId } from "@posthog/core/support/ticketTaskLink";
import { Badge, cn, Text } from "@posthog/quill";
import {
  formatTicketAge,
  SLA_TEXT_CLASSES,
  TICKET_ATTENTION_LABELS,
  TICKET_ATTENTION_VARIANTS,
  ticketRequesterName,
} from "@posthog/ui/features/support/ticketPresentation";

export function TicketRow({
  ticket,
  isActive,
  now,
  onSelect,
}: {
  ticket: SupportTicket;
  isActive: boolean;
  now: number;
  onSelect: () => void;
}) {
  const attention = ticketAttention(ticket, now);
  const sla = ticketSlaState(ticket, now);
  const hasUnread = (ticket.unread_team_count ?? 0) > 0;
  const hasAgentThread = readTicketTaskId(ticket.tags) !== null;
  // Attached pull requests only: a thread's own live in its task, and fetching
  // one per row to decorate a badge is not worth the requests. The ticket shows
  // both.
  const prUrls = readTicketPrUrls(ticket.tags);

  return (
    <button
      type="button"
      onClick={onSelect}
      data-active={isActive || undefined}
      className={cn(
        "flex w-full cursor-default flex-col gap-1 rounded-(--radius-2) px-2 py-1.5 text-left transition-colors",
        "hover:bg-fill-hover data-active:bg-fill-selected",
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span
          aria-hidden
          className={cn(
            "size-2 shrink-0 rounded-full",
            hasUnread ? "bg-primary" : "bg-transparent",
          )}
        />
        <Text className="min-w-0 flex-1 truncate font-medium text-[13px]">
          {ticketRequesterName(ticket)}
        </Text>
        <Text className="shrink-0 text-[11px] text-gray-11 tabular-nums">
          {formatTicketAge(ticket.last_message_at ?? ticket.updated_at, now)}
        </Text>
      </div>

      <Text className="truncate pl-3.5 text-[12px] text-muted-foreground leading-snug">
        {ticket.last_message_text || `#${ticket.ticket_number}`}
      </Text>

      <div className="flex min-w-0 items-center gap-1.5 pl-3.5">
        <Badge variant={TICKET_ATTENTION_VARIANTS[attention]}>
          {TICKET_ATTENTION_LABELS[attention]}
        </Badge>
        {hasAgentThread && <Badge variant="default">Agent</Badge>}
        {prUrls.length > 0 && (
          <Badge variant="default">
            <GitPullRequestIcon size={10} />
            {prNumberLabel(prUrls)}
          </Badge>
        )}
        {sla !== "none" && (
          <Text
            className={cn(
              "ml-auto shrink-0 text-[11px] tabular-nums",
              SLA_TEXT_CLASSES[sla],
            )}
          >
            {sla === "breached" ? "overdue" : "SLA"}
          </Text>
        )}
      </div>
    </button>
  );
}

/** The first pull request, with a count for the rest, as task rows do. */
function prNumberLabel(prUrls: string[]): string {
  const first = prUrls[0]?.match(/\/pull\/(\d+)/)?.[1];
  const label = first ? `#${first}` : "PR";
  return prUrls.length > 1 ? `${label} +${prUrls.length - 1}` : label;
}
