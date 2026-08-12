import { TicketIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { TicketList } from "@posthog/ui/features/support/components/TicketList";
import { useAppView } from "@posthog/ui/router/useAppView";
import { Outlet } from "@tanstack/react-router";

const TICKET_LIST_WIDTH_CLASS = "w-[280px]";

export function SupportView() {
  const view = useAppView();
  const activeTicketId = view.type === "support" ? view.ticketId : undefined;

  return (
    <div className="flex h-full min-h-0">
      <div
        className={`${TICKET_LIST_WIDTH_CLASS} shrink-0 border-border border-r`}
      >
        <TicketList activeTicketId={activeTicketId} />
      </div>
      <div className="min-w-0 flex-1">
        {activeTicketId ? <Outlet /> : <NoTicketSelected />}
      </div>
    </div>
  );
}

function NoTicketSelected() {
  return (
    <Empty className="h-full">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <TicketIcon size={18} />
        </EmptyMedia>
        <EmptyTitle>Pick a ticket</EmptyTitle>
        <EmptyDescription>
          Its conversation, context and agent thread open here.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}
