import type { Ticket } from "@posthog/api-client/posthog-client";
import type { AttentionState } from "@posthog/core/support/attention";
import { Badge } from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import {
  assigneeDisplay,
  channelLabel,
  hasPriority,
  priorityLabel,
  requesterLabel,
  statusLabel,
  ticketPreview,
} from "../ticketPresentation";
import { AttentionChip } from "./AttentionChip";

interface TicketRowProps {
  ticket: Ticket;
  state: AttentionState;
  onClick: () => void;
}

const STATUS_BADGE_VARIANT: Record<
  string,
  "default" | "info" | "warning" | "success" | "completed"
> = {
  new: "info",
  open: "default",
  pending: "warning",
  on_hold: "default",
  resolved: "completed",
};

export function TicketRow({ ticket, state, onClick }: TicketRowProps) {
  const assignee = assigneeDisplay(ticket.assignee);
  const preview = ticketPreview(ticket);

  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full cursor-pointer rounded-md px-3 py-2 text-left hover:bg-(--gray-3)"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="shrink-0 font-medium text-[13px]">
          {requesterLabel(ticket)}
        </span>
        {ticket.unread_team_count > 0 && (
          <Badge variant="info">{ticket.unread_team_count} new</Badge>
        )}
        <span className="min-w-0 flex-1 truncate text-(--gray-10) text-[13px]">
          {preview}
        </span>
        <RelativeTimestamp
          timestamp={ticket.last_message_at ?? ticket.updated_at}
        />
      </div>
      <div className="mt-1 flex min-w-0 items-center gap-2">
        {/* The reason chip explains this row's rank; SLA urgency lives here. */}
        <AttentionChip state={state} ticket={ticket} />
        <Badge variant={STATUS_BADGE_VARIANT[ticket.status ?? "new"]}>
          {statusLabel(ticket.status)}
        </Badge>
        {/* Untriaged is a distinct state — never render it as low priority. */}
        <Badge variant={hasPriority(ticket.priority) ? "default" : "warning"}>
          {priorityLabel(ticket.priority)}
        </Badge>
        <span className="text-(--gray-9) text-[11px]">
          {channelLabel(ticket.channel_source)}
        </span>
        <span className="ml-auto shrink-0 text-(--gray-9) text-[11px]">
          {assignee.kind === "role"
            ? `${assignee.label} (pool)`
            : assignee.label}
        </span>
      </div>
    </button>
  );
}
