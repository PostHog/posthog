import { PushPinIcon, TicketIcon } from "@phosphor-icons/react";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { ticketSlaState } from "@posthog/core/support/ticketState";
import {
  Badge,
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { PanelResizeHandle } from "@posthog/ui/features/panels/components/PanelResizeHandle";
import { TicketComposer } from "@posthog/ui/features/support/components/TicketComposer";
import { TicketSidebar } from "@posthog/ui/features/support/components/TicketSidebar";
import { TicketThread } from "@posthog/ui/features/support/components/TicketThread";
import { useSupportTicketMessages } from "@posthog/ui/features/support/hooks/useSupportTicketMessages";
import { usePinnedTicketsStore } from "@posthog/ui/features/support/pinnedTicketsStore";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import {
  isTicketNotFoundError,
  supportTicketQuery,
} from "@posthog/ui/features/support/supportQueries";
import { useSupportQueueStore } from "@posthog/ui/features/support/supportQueueStore";
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
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Panel, PanelGroup } from "react-resizable-panels";

const TICKET_SIDEBAR_MIN_WIDTH = 400;

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

  const sidebarWidth = useSupportQueueStore((state) => state.sidebarWidth);
  const { setSidebarWidth } = useSupportQueueStore.getState();
  const [isResizing, setIsResizing] = useState(false);

  const queryClient = useQueryClient();
  const readTicketId = ticket?.id;
  useEffect(() => {
    if (!readTicketId) {
      return;
    }
    queryClient.invalidateQueries({ queryKey: supportKeys.ticketLists() });
  }, [readTicketId, queryClient]);

  if (isPending && !ticket) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-4 text-gray-9" />
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
    <div className="flex h-full min-h-0 flex-col">
      <TicketHeader ticket={ticket} />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-[32px] shrink-0 items-center gap-1.5 border-border border-b px-3">
            <Text className="font-medium text-[13px]">Conversation</Text>
            <CountBadge count={messages.length} tone="neutral" />
          </div>
          <PanelGroup
            direction="vertical"
            autoSaveId="support-ticket-thread"
            className="min-h-0 flex-1"
          >
            <Panel
              defaultSize={65}
              minSize={25}
              className="flex min-h-0 flex-col"
            >
              <TicketThread messages={messages} />
            </Panel>
            <PanelResizeHandle className="h-px bg-(--gray-5) transition-colors hover:bg-(--gray-7) data-[resize-handle-state=drag]:bg-(--accent-9)" />
            <Panel
              defaultSize={35}
              minSize={15}
              className="flex min-h-0 flex-col"
            >
              <TicketComposer key={ticket.id} ticket={ticket} />
            </Panel>
          </PanelGroup>
        </div>
        <ResizableSidebar
          open
          width={sidebarWidth}
          setWidth={setSidebarWidth}
          isResizing={isResizing}
          setIsResizing={setIsResizing}
          minWidth={TICKET_SIDEBAR_MIN_WIDTH}
          side="right"
        >
          <TicketSidebar key={ticket.id} ticket={ticket} messages={messages} />
        </ResizableSidebar>
      </div>
    </div>
  );
}

function TicketHeader({ ticket }: { ticket: SupportTicket }) {
  const now = Date.now();
  const sla = ticketSlaState(ticket, now);
  const countdown = formatSlaCountdown(ticket.sla_due_at, now);
  const pinned = usePinnedTicketsStore(
    (state) => state.pinnedAtById[ticket.id] !== undefined,
  );
  const { togglePinned } = usePinnedTicketsStore.getState();

  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-border border-b px-3">
      <Text className="min-w-0 shrink truncate font-medium text-[13px]">
        {ticket.email_subject || ticketRequesterName(ticket)}
      </Text>
      <Text className="min-w-0 shrink-[2] truncate text-[12px] text-muted-foreground">
        {`#${ticket.ticket_number} · ${ticket.channel_source} · ${ticketRequesterName(ticket)}`}
      </Text>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="default"
              size="icon-sm"
              aria-label={pinned ? "Unpin ticket" : "Pin ticket"}
              onClick={() => togglePinned(ticket.id)}
              className="text-muted-foreground"
            >
              <PushPinIcon
                size={16}
                weight={pinned ? "fill" : "regular"}
                className={pinned ? "text-primary" : undefined}
              />
            </Button>
          }
        />
        <TooltipContent side="bottom">
          {pinned ? "Unpin from My tickets" : "Pin to My tickets"}
        </TooltipContent>
      </Tooltip>

      <div className="ml-auto flex shrink-0 items-center gap-1.5">
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
