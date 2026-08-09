import {
  ClockCounterClockwiseIcon,
  PulseIcon,
  TicketIcon,
  UserIcon,
} from "@phosphor-icons/react";
import type { Ticket, TicketMessage } from "@posthog/api-client/posthog-client";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { navigateToSupportTicketDetail } from "@posthog/ui/router/navigationBridge";
import { useSupportTickets } from "../hooks/useSupportTickets";
import {
  channelLabel,
  customerTicketHistory,
  requesterEmail,
  requesterLabel,
  STATUS_PILL_CLASS,
  statusLabel,
  ticketActivityEntries,
  ticketPreview,
} from "../ticketPresentation";
import { CardRow, SidebarCard, StateLine } from "./SidebarCard";
import { TicketActions } from "./TicketActions";

// One extra over the display cap so the card can say how many are hidden.
const HISTORY_LIMIT = 8;

/**
 * The ticket's context column: who it's from, the fields you can change, and
 * what has already happened. Split across two tabs because the column is
 * narrow and the two halves answer different questions — "what do I change"
 * versus "what happened".
 */
export function TicketSidebar({
  ticket,
  messages,
}: {
  ticket: Ticket;
  messages: TicketMessage[] | undefined;
}) {
  return (
    <aside className="flex h-full min-h-0 w-80 shrink-0 flex-col overflow-hidden border-border border-l bg-card">
      <Tabs defaultValue="ticket" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="shrink-0">
          <TabsTrigger value="ticket">Ticket</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
        </TabsList>
        <TabsContent
          value="ticket"
          className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3"
        >
          <AccountCard ticket={ticket} />
          <TicketFieldsCard ticket={ticket} />
        </TabsContent>
        <TabsContent
          value="activity"
          className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3"
        >
          <ActivityCard ticket={ticket} messages={messages} />
          {/* Mounted only when we have an identity to match on, so the card
              never fires a lookup it can't scope. */}
          {requesterEmail(ticket) && <HistoryCard ticket={ticket} />}
        </TabsContent>
      </Tabs>
    </aside>
  );
}

function AccountCard({ ticket }: { ticket: Ticket }) {
  const email = requesterEmail(ticket);
  const label = requesterLabel(ticket);
  return (
    <SidebarCard title="Account" icon={<UserIcon size={13} />}>
      <div className="space-y-1">
        <CardRow label="Name" value={label} />
        <CardRow label="Email" value={email === label ? null : email} />
        <CardRow
          label="Identity"
          value={ticket.person ? "Identified person" : "Anonymous"}
        />
      </div>
    </SidebarCard>
  );
}

function TicketFieldsCard({ ticket }: { ticket: Ticket }) {
  return (
    <SidebarCard title="Ticket" icon={<TicketIcon size={13} />}>
      <TicketActions ticket={ticket} />
      {/* Channel context is information, not an action, so it sits below the
          editable fields rather than mixed in with them. */}
      <div className="mt-2 space-y-1 border-border border-t pt-2">
        <CardRow label="Channel" value={channelLabel(ticket.channel_source)} />
        <CardRow label="Subject" value={ticket.email_subject} />
        <CardRow label="From" value={ticket.email_from} />
        <CardRow label="To" value={ticket.email_to} />
        <CardRow label="CC" value={ccParticipants(ticket)} />
      </div>
    </SidebarCard>
  );
}

// cc_participants is untyped on the wire — treat anything that isn't a list of
// addresses as absent rather than rendering "[object Object]".
function ccParticipants(ticket: Ticket): string | null {
  const cc = ticket.cc_participants;
  if (!Array.isArray(cc) || cc.length === 0) return null;
  return cc.filter((entry) => typeof entry === "string").join(", ") || null;
}

function ActivityCard({
  ticket,
  messages,
}: {
  ticket: Ticket;
  messages: TicketMessage[] | undefined;
}) {
  const entries = ticketActivityEntries(ticket, messages);
  return (
    <SidebarCard title="Activity" icon={<PulseIcon size={13} />}>
      {messages === undefined ? (
        <StateLine kind="loading">Loading…</StateLine>
      ) : (
        <ul className="space-y-px">
          {entries.map((entry) => (
            <li
              key={entry.id}
              className="flex items-baseline gap-3 rounded px-1 py-1 text-[11px] leading-relaxed hover:bg-muted/40"
            >
              <span className="min-w-0 flex-1">
                <span className="font-medium text-foreground">
                  {entry.actor}
                </span>{" "}
                <span className="break-words text-muted-foreground">
                  {entry.label}
                </span>
              </span>
              <RelativeTimestamp timestamp={entry.at} />
            </li>
          ))}
        </ul>
      )}
    </SidebarCard>
  );
}

/**
 * Every ticket this customer has opened, so a repeat problem is visible
 * without leaving the thread. Matched on the requester's email — the list
 * endpoint has no identity filter, so this searches for it and keeps the
 * tickets that really belong to them.
 */
function HistoryCard({ ticket }: { ticket: Ticket }) {
  const { data, isPending, isError } = useSupportTickets({
    search: requesterEmail(ticket) ?? "",
    orderBy: "-updated_at",
    limit: 25,
  });

  const { entries, extra } = customerTicketHistory(
    data?.results ?? [],
    ticket,
    HISTORY_LIMIT,
  );

  return (
    <SidebarCard
      title="Ticket history"
      icon={<ClockCounterClockwiseIcon size={13} />}
      trailing={
        <span className="rounded-full bg-muted px-1.5 font-medium text-[10px] text-muted-foreground">
          {entries.length + extra}
        </span>
      }
    >
      {isPending && <StateLine kind="loading">Loading…</StateLine>}
      {isError && (
        <StateLine kind="error">
          Couldn't load this customer's tickets.
        </StateLine>
      )}
      {!isPending && !isError && (
        <ul className="space-y-0.5">
          {entries.map((entry) => (
            <HistoryRow
              key={entry.ticket.id}
              ticket={entry.ticket}
              isCurrent={entry.isCurrent}
            />
          ))}
        </ul>
      )}
      {extra > 0 && (
        <div className="mt-2 text-[11px] text-muted-foreground">
          +{extra} earlier
        </div>
      )}
    </SidebarCard>
  );
}

function HistoryRow({
  ticket,
  isCurrent,
}: {
  ticket: Ticket;
  isCurrent: boolean;
}) {
  const inner = (
    <>
      <span
        className={`shrink-0 rounded-full px-1.5 py-px font-medium text-[9px] uppercase tracking-wide ${
          STATUS_PILL_CLASS[ticket.status ?? "new"] ??
          "bg-muted text-foreground"
        }`}
      >
        {statusLabel(ticket.status)}
      </span>
      <span className="min-w-0 flex-1 truncate text-foreground">
        {ticketPreview(ticket) || `Ticket #${ticket.ticket_number}`}
      </span>
      <RelativeTimestamp timestamp={ticket.updated_at} />
    </>
  );

  // The open ticket renders as a static "you are here" row rather than a link
  // that would navigate to the page you're already on.
  if (isCurrent) {
    return (
      <li>
        <div
          aria-current="page"
          className="flex items-center gap-2 rounded border-primary border-l-2 bg-muted/40 px-1 py-1 pl-2 text-[12px]"
        >
          {inner}
        </div>
      </li>
    );
  }
  return (
    <li>
      <button
        type="button"
        onClick={() => navigateToSupportTicketDetail(ticket.id)}
        className="flex w-full cursor-pointer items-center gap-2 rounded px-1 py-1 text-left text-[12px] hover:bg-muted"
      >
        {inner}
      </button>
    </li>
  );
}
