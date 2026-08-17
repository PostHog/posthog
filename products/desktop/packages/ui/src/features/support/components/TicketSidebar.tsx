import { InfoIcon, RobotIcon } from "@phosphor-icons/react";
import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import { readTicketTaskId } from "@posthog/core/support/ticketTaskLink";
import { Text } from "@posthog/quill";
import { TicketAgentPanel } from "@posthog/ui/features/support/components/TicketAgentPanel";
import { TicketInfoPanel } from "@posthog/ui/features/support/components/TicketInfoPanel";
import {
  type SupportSidebarTab,
  useSupportQueueStore,
} from "@posthog/ui/features/support/supportQueueStore";
import {
  type PanelSide,
  PanelSideSwitcher,
} from "@posthog/ui/primitives/PanelSideSwitcher";
import { useEffect } from "react";

const SIDES: readonly PanelSide<SupportSidebarTab>[] = [
  { key: "ticket", label: "Ticket", Icon: InfoIcon },
  { key: "agent", label: "AI chat", Icon: RobotIcon },
];

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

  const activeLabel = SIDES.find((side) => side.key === tab)?.label;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-[32px] shrink-0 items-center gap-1 border-b border-b-(--gray-6) pr-1 pl-2">
        <Text className="font-medium text-[13px]">{activeLabel}</Text>
        <div className="ml-auto">
          <PanelSideSwitcher
            sides={SIDES}
            active={tab}
            onSelect={(side) => setSidebarTab(side ?? tab)}
          />
        </div>
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
