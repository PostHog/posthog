import { TicketIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { TicketList } from "@posthog/ui/features/support/components/TicketList";
import { useSupportQueueStore } from "@posthog/ui/features/support/supportQueueStore";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useAppView } from "@posthog/ui/router/useAppView";
import { Outlet } from "@tanstack/react-router";
import { useState } from "react";

export function SupportView() {
  const view = useAppView();
  const activeTicketId = view.type === "support" ? view.ticketId : undefined;
  const listWidth = useSupportQueueStore((state) => state.listWidth);
  const { setListWidth } = useSupportQueueStore.getState();
  const [isResizing, setIsResizing] = useState(false);

  return (
    <div className="flex h-full min-h-0">
      <ResizableSidebar
        open
        width={listWidth}
        setWidth={setListWidth}
        isResizing={isResizing}
        setIsResizing={setIsResizing}
        side="left"
      >
        <TicketList activeTicketId={activeTicketId} />
      </ResizableSidebar>
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
