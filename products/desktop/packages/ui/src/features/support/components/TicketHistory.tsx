import {
  SUPPORT_HISTORY_PAGE_SIZE,
  type SupportTicket,
} from "@posthog/api-client/posthog-client";
import { Badge, Text } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { Section } from "@posthog/ui/features/support/components/TicketRailSection";
import { useSupportTickets } from "@posthog/ui/features/support/hooks/useSupportTickets";
import {
  TICKET_STATUS_VARIANTS,
  ticketStatusLabel,
} from "@posthog/ui/features/support/ticketPresentation";
import { navigateToSupportTicket } from "@posthog/ui/router/navigationBridge";
import { useMemo } from "react";

export function TicketHistory({ ticket }: { ticket: SupportTicket }) {
  const distinctIds = useMemo(() => {
    const merged = ticket.person?.distinct_ids ?? [];
    if (merged.length > 0) {
      return merged;
    }
    return ticket.distinct_id ? [ticket.distinct_id] : [];
  }, [ticket.person?.distinct_ids, ticket.distinct_id]);

  const { data } = useSupportTickets(
    {
      distinctIds,
      orderBy: "-created_at",
      limit: SUPPORT_HISTORY_PAGE_SIZE,
    },
    { enabled: distinctIds.length > 0, refetchInterval: false },
  );

  const others = (data?.results ?? []).filter((row) => row.id !== ticket.id);
  if (others.length === 0) {
    return null;
  }

  return (
    <Section
      title="Earlier tickets"
      trailing={
        <Text className="text-[10px] text-muted-foreground tabular-nums">
          {others.length}
        </Text>
      }
    >
      <div className="flex flex-col py-0.5">
        {others.map((row) => (
          <button
            key={row.id}
            type="button"
            onClick={() => navigateToSupportTicket(row.id)}
            className="flex cursor-default items-center gap-2 rounded-(--radius-2) px-1 py-1 text-left hover:bg-fill-hover"
          >
            <Text className="min-w-0 flex-1 truncate text-[12px]">
              {row.email_subject || `#${row.ticket_number}`}
            </Text>
            <Badge variant={TICKET_STATUS_VARIANTS[row.status ?? "new"]}>
              {ticketStatusLabel(row.status)}
            </Badge>
            <Text className="shrink-0 text-[10px] text-gray-11 tabular-nums">
              {formatRelativeTimeShort(row.created_at)}
            </Text>
          </button>
        ))}
      </div>
    </Section>
  );
}
