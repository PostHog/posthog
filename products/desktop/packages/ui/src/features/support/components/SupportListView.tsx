import { LifebuoyIcon } from "@phosphor-icons/react";
import { rankQueue } from "@posthog/core/support/attention";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { navigateToSupportTicketDetail } from "@posthog/ui/router/navigationBridge";
import { useMemo } from "react";
import { useSupportTickets } from "../hooks/useSupportTickets";
import { TicketRow } from "./TicketRow";

/**
 * The attention queue: tickets ranked by what needs attention now, every row
 * carrying the reason for its rank. Ranking is pure core logic
 * (@posthog/core/support/attention); this view just fetches and renders.
 */
export function SupportListView() {
  const { data, isPending, isError } = useSupportTickets({
    orderBy: "-updated_at",
  });
  // One clock per data refresh keeps classification consistent across rows
  // and the order stable between renders.
  const ranked = useMemo(
    () => rankQueue(data?.results ?? [], new Date()),
    [data],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 px-4 pt-4 pb-2">
        <h2 className="font-semibold text-[18px]">Support</h2>
        {data && (
          <span className="text-(--gray-10) text-[12px]">
            {ranked.length} open
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {isPending && (
          <Empty className="h-full border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Spinner />
              </EmptyMedia>
              <EmptyTitle>Loading tickets</EmptyTitle>
            </EmptyHeader>
          </Empty>
        )}
        {isError && (
          <Empty className="h-full border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <LifebuoyIcon size={20} />
              </EmptyMedia>
              <EmptyTitle>Couldn't load tickets</EmptyTitle>
              <EmptyDescription>
                Check that Conversations is enabled for this project, then try
                again.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        {!isPending && !isError && ranked.length === 0 && (
          <Empty className="h-full border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <LifebuoyIcon size={20} />
              </EmptyMedia>
              <EmptyTitle>No tickets</EmptyTitle>
              <EmptyDescription>
                Customer tickets from Conversations will show up here.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        {ranked.map(({ ticket, state }) => (
          <TicketRow
            key={ticket.id}
            ticket={ticket}
            state={state}
            onClick={() => navigateToSupportTicketDetail(ticket.id)}
          />
        ))}
      </div>
    </div>
  );
}
