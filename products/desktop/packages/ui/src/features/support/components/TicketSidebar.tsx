import { type Icon, InfoIcon, RobotIcon } from "@phosphor-icons/react";
import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import { readTicketTaskId } from "@posthog/core/support/ticketTaskLink";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { TicketAgentPanel } from "@posthog/ui/features/support/components/TicketAgentPanel";
import { TicketInfoPanel } from "@posthog/ui/features/support/components/TicketInfoPanel";
import {
  type SupportSidebarTab,
  useSupportQueueStore,
} from "@posthog/ui/features/support/supportQueueStore";
import { useEffect } from "react";

const SIDEBAR_TABS: Record<SupportSidebarTab, { label: string; Icon: Icon }> = {
  ticket: { label: "Ticket", Icon: InfoIcon },
  agent: { label: "AI chat", Icon: RobotIcon },
};

const SIDEBAR_TAB_ORDER: readonly SupportSidebarTab[] = ["ticket", "agent"];

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
      <div className="flex h-[32px] shrink-0 items-center gap-0.5 border-border border-b pr-2 pl-3">
        <span className="min-w-0 flex-1 truncate font-medium text-[13px]">
          {SIDEBAR_TABS[tab].label}
        </span>
        {SIDEBAR_TAB_ORDER.map((side) => (
          <SidebarTabButton
            key={side}
            side={side}
            active={tab}
            onSelect={setSidebarTab}
          />
        ))}
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

function SidebarTabButton({
  side,
  active,
  onSelect,
}: {
  side: SupportSidebarTab;
  active: SupportSidebarTab;
  onSelect: (tab: SupportSidebarTab) => void;
}) {
  const { label, Icon } = SIDEBAR_TABS[side];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={label}
            data-selected={active === side || undefined}
            onClick={() => onSelect(side)}
            className="text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          >
            <Icon size={16} />
          </Button>
        }
      />
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}
