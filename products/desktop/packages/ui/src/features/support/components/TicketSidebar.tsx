import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import { readTicketTaskId } from "@posthog/core/support/ticketTaskLink";
import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { TicketAgentPanel } from "@posthog/ui/features/support/components/TicketAgentPanel";
import { TicketInfoPanel } from "@posthog/ui/features/support/components/TicketInfoPanel";
import {
  type SupportSidebarTab,
  useSupportQueueStore,
} from "@posthog/ui/features/support/supportQueueStore";
import { useEffect } from "react";

/**
 * The right rail: ticket context, or the agent thread.
 *
 * Both panels stay mounted so switching tabs never tears down a live agent
 * session. The agent tab takes the front when a ticket already has a thread,
 * because the reason to come back to such a ticket is usually what the agent
 * did while you were elsewhere.
 */
export function TicketSidebar({
  ticket,
  messages,
}: {
  ticket: SupportTicket;
  messages: SupportTicketMessage[];
}) {
  const tab = useSupportQueueStore((state) => state.sidebarTab);
  const { setSidebarTab } = useSupportQueueStore.getState();
  const hasThread = readTicketTaskId(ticket.tags) !== null;

  useEffect(() => {
    if (hasThread) {
      setSidebarTab("agent");
    }
  }, [hasThread, setSidebarTab]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center border-border border-b pr-1 pl-2">
        <Tabs
          value={tab}
          onValueChange={(value) => setSidebarTab(value as SupportSidebarTab)}
        >
          <TabsList variant="line" className="h-[31px] gap-0.5 p-0">
            <TabsTrigger value="ticket" className="px-2.5">
              Ticket
            </TabsTrigger>
            <TabsTrigger value="agent" className="px-2.5">
              AI chat
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto" hidden={tab !== "ticket"}>
        <TicketInfoPanel ticket={ticket} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col" hidden={tab !== "agent"}>
        <TicketAgentPanel ticket={ticket} messages={messages} />
      </div>
    </div>
  );
}
