import {
  ChatCircleIcon,
  EnvelopeSimpleIcon,
  GlobeIcon,
  type Icon,
  MicrosoftTeamsLogoIcon,
  SlackLogoIcon,
} from "@phosphor-icons/react";
import type { Ticket } from "@posthog/api-client/posthog-client";
import type { AttentionState } from "@posthog/core/support/attention";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { memo, type ReactNode } from "react";
import {
  assigneeDisplay,
  channelLabel,
  PRIORITY_PILL_CLASS,
  priorityLabel,
  type QueueColumn,
  requesterLabel,
  SLA_STRIPE_CLASS,
  SLA_TEXT_CLASS,
  STATUS_PILL_CLASS,
  slaCountdownLabel,
  slaTone,
  statusLabel,
  ticketPreview,
} from "../ticketPresentation";
import { AttentionChip } from "./AttentionChip";

const CHANNEL_ICONS: Record<string, Icon> = {
  email: EnvelopeSimpleIcon,
  slack: SlackLogoIcon,
  teams: MicrosoftTeamsLogoIcon,
  widget: ChatCircleIcon,
};

interface TicketRowProps {
  ticket: Ticket;
  state: AttentionState;
  /** Visible columns in order — the row carries no per-column conditionals. */
  columns: readonly QueueColumn[];
  /** One clock for the whole list, so no two rows disagree about "now". */
  now: Date;
  onClick: () => void;
}

export const TicketRow = memo(function TicketRow({
  ticket,
  state,
  columns,
  now,
  onClick,
}: TicketRowProps) {
  const tone = slaTone(ticket.sla_due_at, now);

  return (
    <li className="flex min-w-0 items-stretch bg-card hover:bg-fill-hover">
      {/* Colour-codes the row by SLA urgency at a glance. Tickets without an
          SLA keep a transparent stripe so every row stays aligned. */}
      <span aria-hidden className={`w-1 shrink-0 ${SLA_STRIPE_CLASS[tone]}`} />
      <button
        type="button"
        onClick={onClick}
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 py-2.5 pr-4 pl-3 text-left"
      >
        {columns.map((column) => (
          <div key={column.id} className={column.className}>
            <TicketCell
              column={column}
              ticket={ticket}
              state={state}
              now={now}
            />
          </div>
        ))}
      </button>
    </li>
  );
});

function TicketCell({
  column,
  ticket,
  state,
  now,
}: {
  column: QueueColumn;
  ticket: Ticket;
  state: AttentionState;
  now: Date;
}) {
  switch (column.id) {
    case "number":
      return (
        <span className="font-mono text-[11px] text-muted-foreground">
          #{ticket.ticket_number}
        </span>
      );
    case "status":
      return (
        <Pill
          className={
            STATUS_PILL_CLASS[ticket.status ?? "new"] ??
            "bg-muted text-foreground"
          }
        >
          {statusLabel(ticket.status)}
        </Pill>
      );
    case "channel":
      return <ChannelCell ticket={ticket} />;
    case "priority":
      return (
        <Pill
          className={
            PRIORITY_PILL_CLASS[ticket.priority ?? "none"] ??
            PRIORITY_PILL_CLASS.none
          }
        >
          {priorityLabel(ticket.priority)}
        </Pill>
      );
    case "customer":
      return <CustomerCell ticket={ticket} state={state} />;
    case "sla":
      return <SlaCell ticket={ticket} now={now} />;
    case "assignee": {
      const assignee = assigneeDisplay(ticket.assignee);
      return (
        <span className="truncate text-[12px] text-muted-foreground">
          {assignee.kind === "role"
            ? `${assignee.label} (pool)`
            : assignee.label}
        </span>
      );
    }
    case "updated":
      return (
        <div className="flex justify-end">
          <RelativeTimestamp timestamp={ticket.updated_at} />
        </div>
      );
  }
}

function Pill({
  className,
  children,
}: {
  className: string;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 font-medium text-[11px] ${className}`}
    >
      {children}
    </span>
  );
}

function ChannelCell({ ticket }: { ticket: Ticket }) {
  const source =
    typeof ticket.channel_source === "string" ? ticket.channel_source : "";
  const ChannelIcon = CHANNEL_ICONS[source] ?? GlobeIcon;
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
      {ticket.unread_team_count > 0 ? (
        <span
          role="img"
          aria-label="Unread customer messages"
          className="size-1.5 shrink-0 rounded-full bg-primary"
        />
      ) : (
        <span aria-hidden className="size-1.5 shrink-0" />
      )}
      <ChannelIcon size={14} className="shrink-0" />
      <span className="min-w-0 truncate text-[12px]">
        {channelLabel(ticket.channel_source)}
      </span>
    </div>
  );
}

/**
 * The one cell the Display menu can't switch off, because it carries the
 * attention chip: a ranking nobody can see the reason for gets ignored.
 */
function CustomerCell({
  ticket,
  state,
}: {
  ticket: Ticket;
  state: AttentionState;
}) {
  const preview = ticketPreview(ticket);
  return (
    <>
      <div className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 truncate font-medium text-[13px]">
          {requesterLabel(ticket)}
        </span>
        <AttentionChip state={state} ticket={ticket} />
      </div>
      <div className="truncate text-[12px] text-muted-foreground">
        {preview || "—"}
      </div>
    </>
  );
}

function SlaCell({ ticket, now }: { ticket: Ticket; now: Date }) {
  const tone = slaTone(ticket.sla_due_at, now);
  const countdown = slaCountdownLabel(ticket.sla_due_at, now);
  if (tone === "none" || !countdown) {
    return <span className="text-[12px] text-muted-foreground">—</span>;
  }
  return (
    <span className={`font-medium text-[12px] ${SLA_TEXT_CLASS[tone]}`}>
      {countdown}
    </span>
  );
}
