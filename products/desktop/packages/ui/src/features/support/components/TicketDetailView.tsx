import { SpinnerGapIcon, TicketIcon } from "@phosphor-icons/react";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { ticketSlaState } from "@posthog/core/support/ticketState";
import {
  Badge,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Text,
} from "@posthog/quill";
import { TicketComposer } from "@posthog/ui/features/support/components/TicketComposer";
import { TicketSidebar } from "@posthog/ui/features/support/components/TicketSidebar";
import { TicketThread } from "@posthog/ui/features/support/components/TicketThread";
import { useSupportTicketMessages } from "@posthog/ui/features/support/hooks/useSupportTicketMessages";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import {
  isTicketNotFoundError,
  supportTicketQuery,
} from "@posthog/ui/features/support/supportQueries";
import {
  formatSlaCountdown,
  SLA_TEXT_CLASSES,
  TICKET_PRIORITY_VARIANTS,
  TICKET_STATUS_VARIANTS,
  ticketPriorityLabel,
  ticketRequesterName,
  ticketStatusLabel,
} from "@posthog/ui/features/support/ticketPresentation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

const TICKET_SIDEBAR_WIDTH_CLASS = "w-[340px]";

export function TicketDetailView({
  ticketId,
  cachedTicket,
}: {
  ticketId: string;
  cachedTicket: SupportTicket | null;
}) {
  const {
    data: ticket,
    isPending,
    error,
  } = useQuery({
    ...supportTicketQuery(ticketId),
    initialData: cachedTicket ?? undefined,
  });

  const { data: thread } = useSupportTicketMessages(ticketId);
  const messages = thread?.results ?? [];

  const queryClient = useQueryClient();
  const readTicketId = ticket?.id;
  useEffect(() => {
    if (!readTicketId) {
      return;
    }
    queryClient.invalidateQueries({ queryKey: supportKeys.ticketLists() });
    queryClient.invalidateQueries({ queryKey: supportKeys.unreadCount() });
  }, [readTicketId, queryClient]);

  if (isPending && !ticket) {
    return (
      <div className="flex h-full items-center justify-center">
        <SpinnerGapIcon size={18} className="animate-spin text-gray-9" />
      </div>
    );
  }

  if (!ticket) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <TicketIcon size={18} />
          </EmptyMedia>
          <EmptyTitle>
            {isTicketNotFoundError(error)
              ? "This ticket does not exist"
              : "Could not load this ticket"}
          </EmptyTitle>
          <EmptyDescription>
            {isTicketNotFoundError(error)
              ? "It may have been deleted, or it belongs to another project."
              : "Pick another ticket, or try again in a moment."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <TicketHeader ticket={ticket} />
        <TicketThread messages={messages} />
        <TicketComposer key={ticket.id} ticket={ticket} />
      </div>
      <div
        className={cn(
          "shrink-0 border-border border-l",
          TICKET_SIDEBAR_WIDTH_CLASS,
        )}
      >
        <TicketSidebar key={ticket.id} ticket={ticket} messages={messages} />
      </div>
    </div>
  );
}

function TicketHeader({ ticket }: { ticket: SupportTicket }) {
  const now = Date.now();
  const sla = ticketSlaState(ticket, now);
  const countdown = formatSlaCountdown(ticket.sla_due_at, now);

  return (
    <div className="flex shrink-0 items-start gap-3 border-border border-b px-4 py-3">
      <div className="min-w-0 flex-1">
        <Text className="block truncate font-semibold text-[15px] leading-tight">
          {ticket.email_subject || ticketRequesterName(ticket)}
        </Text>
        <Text className="mt-0.5 block truncate text-[12px] text-muted-foreground">
          {`#${ticket.ticket_number} · ${ticket.channel_source} · ${ticketRequesterName(ticket)}`}
        </Text>
      </div>

      <div className="flex shrink-0 items-center gap-1.5 pt-0.5">
        {countdown && (
          <Text
            className={cn("text-[11px] tabular-nums", SLA_TEXT_CLASSES[sla])}
          >
            {countdown}
          </Text>
        )}
        <Badge variant={TICKET_STATUS_VARIANTS[ticket.status ?? "new"]}>
          {ticketStatusLabel(ticket.status)}
        </Badge>
        {ticket.priority && (
          <Badge variant={TICKET_PRIORITY_VARIANTS[ticket.priority]}>
            {ticketPriorityLabel(ticket.priority)}
          </Badge>
        )}
      </div>
    </div>
  );
}
