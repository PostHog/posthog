import type {
  ListTicketsOptions,
  Ticket,
  TicketAssignment,
  TicketMessage,
} from "@posthog/api-client/posthog-client";
import {
  type ClassifiedTicket,
  SLA_AT_RISK_WINDOW_MS,
} from "@posthog/core/support/attention";

/**
 * Pure display helpers for Conversations tickets. Everything here takes the
 * API shape and returns render-ready values; no I/O, no Date.now() — callers
 * pass `now` so results stay deterministic and testable.
 */

const STATUS_LABELS: Record<string, string> = {
  new: "New",
  open: "Open",
  pending: "Pending",
  on_hold: "On hold",
  resolved: "Resolved",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "New";
  return STATUS_LABELS[status] ?? status;
}

/**
 * Priority is nullable on purpose: an untriaged ticket has no priority yet.
 * Unknown is not low — render it as its own state, never as the bottom of
 * the priority scale.
 */
export function priorityLabel(priority: Ticket["priority"]): string {
  switch (priority) {
    case "low":
      return "Low";
    case "medium":
      return "Medium";
    case "high":
      return "High";
    default:
      return "No priority";
  }
}

export function hasPriority(priority: Ticket["priority"]): boolean {
  return priority === "low" || priority === "medium" || priority === "high";
}

export type AssigneeKind = "user" | "role" | "unassigned";

export interface AssigneeDisplay {
  kind: AssigneeKind;
  label: string;
}

/**
 * TicketAssignment is one-of user/role (DB check constraint). A role
 * assignment is an unclaimed shared pool, not a person — keep the two
 * visually distinct.
 */
export function assigneeDisplay(
  assignee: TicketAssignment | null | undefined,
): AssigneeDisplay {
  const user = assignee?.user;
  if (user) {
    const label = user.first_name || user.email || "Assigned";
    return { kind: "user", label };
  }
  const role = assignee?.role;
  if (role) {
    return { kind: "role", label: role.name || "Role" };
  }
  return { kind: "unassigned", label: "Unassigned" };
}

const CHANNEL_LABELS: Record<string, string> = {
  email: "Email",
  slack: "Slack",
  teams: "Teams",
  widget: "Widget",
};

export function channelLabel(source: Ticket["channel_source"]): string {
  const key = typeof source === "string" ? source : "";
  return CHANNEL_LABELS[key] ?? (key || "Unknown");
}

/**
 * Who the ticket is from, best-effort across channels: identified person,
 * then widget-collected traits, then the email envelope, then the number.
 */
export function requesterLabel(ticket: Ticket): string {
  if (ticket.person?.name) return ticket.person.name;
  const traits = ticket.anonymous_traits;
  if (traits && typeof traits === "object") {
    const t = traits as Record<string, unknown>;
    if (typeof t.name === "string" && t.name) return t.name;
    if (typeof t.email === "string" && t.email) return t.email;
  }
  if (ticket.email_from) return ticket.email_from;
  return `Ticket #${ticket.ticket_number}`;
}

/**
 * Best-effort email for the requester, across identified people, widget
 * traits and the email envelope. Also the key the customer's other tickets
 * are looked up by.
 */
export function requesterEmail(ticket: Ticket): string | null {
  const fromRecord = (value: unknown): string | null => {
    if (!value || typeof value !== "object") return null;
    const email = (value as Record<string, unknown>).email;
    return typeof email === "string" && email ? email : null;
  };
  return (
    fromRecord(ticket.person?.properties) ??
    fromRecord(ticket.anonymous_traits) ??
    ticket.email_from ??
    null
  );
}

/** One-line preview for list rows: subject beats last-message body. */
export function ticketPreview(ticket: Ticket): string {
  return ticket.email_subject || ticket.last_message_text || "";
}

export interface SnoozePreset {
  id: string;
  label: string;
  until: Date;
}

/**
 * Snooze targets for the ticket actions menu. Deterministic for a fixed
 * `now`: morning targets land at 9am local, "next week" is next Monday
 * (a full week away when today is Monday).
 */
export function snoozePresets(now: Date): SnoozePreset[] {
  const inOneHour = new Date(now.getTime() + 60 * 60 * 1000);

  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(9, 0, 0, 0);

  const nextMonday = new Date(now);
  const daysToMonday = (8 - nextMonday.getDay()) % 7 || 7;
  nextMonday.setDate(nextMonday.getDate() + daysToMonday);
  nextMonday.setHours(9, 0, 0, 0);

  return [
    { id: "hour", label: "1 hour", until: inOneHour },
    { id: "tomorrow", label: "Tomorrow, 9am", until: tomorrow },
    { id: "next-week", label: "Next Monday, 9am", until: nextMonday },
  ];
}

/**
 * Urgency band for the queue row's left stripe. The at-risk threshold is the
 * same window the attention ranking uses, so the colour a row shows and the
 * tier it was ranked into can never disagree.
 */
export type SlaTone = "none" | "on-track" | "at-risk" | "breached";

export function slaTone(
  slaDueAt: string | null | undefined,
  now: Date,
): SlaTone {
  const dueMs = parseTime(slaDueAt);
  if (dueMs === null) return "none";
  const remaining = dueMs - now.getTime();
  // `< 0`, not `<= 0`, so an exactly-due ticket lands in the same band the
  // ranking puts it in.
  if (remaining < 0) return "breached";
  return remaining <= SLA_AT_RISK_WINDOW_MS ? "at-risk" : "on-track";
}

/**
 * Compact SLA label for a queue cell, framed around the breach rather than
 * the clock time: "3h left" before, "2h overdue" after.
 */
export function slaCountdownLabel(
  slaDueAt: string | null | undefined,
  now: Date,
): string | null {
  const dueMs = parseTime(slaDueAt);
  if (dueMs === null) return null;
  const diff = dueMs - now.getTime();
  return diff < 0
    ? `${humanizeDuration(-diff)} overdue`
    : `${humanizeDuration(diff)} left`;
}

function humanizeDuration(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

/**
 * Colour-coding shared by the queue and the ticket detail. Semantic tokens
 * only, so these resolve against whatever theme the app is running.
 */
/** Solid accent for the row stripe — the soft `--warning`/`--success` fills are
 *  a background pair and vanish at 4px wide. */
export const SLA_STRIPE_CLASS: Record<SlaTone, string> = {
  none: "bg-transparent",
  "on-track": "bg-success-foreground",
  "at-risk": "bg-warning-foreground",
  breached: "bg-destructive-foreground",
};

export const SLA_TEXT_CLASS: Record<SlaTone, string> = {
  none: "text-muted-foreground",
  "on-track": "text-muted-foreground",
  "at-risk": "text-warning-foreground",
  breached: "text-destructive-foreground",
};

export const STATUS_PILL_CLASS: Record<string, string> = {
  new: "bg-info text-info-foreground",
  open: "bg-warning text-warning-foreground",
  pending: "bg-muted text-foreground",
  on_hold: "bg-muted text-muted-foreground",
  resolved: "bg-success text-success-foreground",
};

/** Untriaged is outlined rather than filled: it is a missing value, not a
 *  fourth level, and must never read as the bottom of the scale. */
export const PRIORITY_PILL_CLASS: Record<string, string> = {
  low: "bg-muted text-muted-foreground",
  medium: "bg-warning text-warning-foreground",
  high: "bg-destructive text-destructive-foreground",
  none: "border border-border bg-card text-warning-foreground",
};

export type QueueColumnId =
  | "number"
  | "status"
  | "channel"
  | "priority"
  | "customer"
  | "sla"
  | "assignee"
  | "updated";

export type QueueSortField =
  | "ticket_number"
  | "status"
  | "channel"
  | "priority"
  | "sla_due_at"
  | "assignee"
  | "updated_at";

export interface QueueColumn {
  id: QueueColumnId;
  label: string;
  /** Shown until the user turns it off in the Display menu. */
  defaultVisible: boolean;
  /** Width/alignment classes applied to both the header cell and the row cell
   *  so the two stay aligned. */
  className: string;
  /** When set, the header cell becomes a sort toggle for this field. */
  sortField?: QueueSortField;
}

/**
 * The customer cell carries the ticket's primary content *and* the attention
 * chip, so it is never offered as a toggle — hiding it would hide the reason
 * a row ranks where it does.
 */
export const ALWAYS_VISIBLE_COLUMN_ID: QueueColumnId = "customer";

/** The column inventory in canonical display order. Order is fixed. */
export const QUEUE_COLUMNS: readonly QueueColumn[] = [
  {
    id: "number",
    label: "#",
    defaultVisible: true,
    className: "w-14 shrink-0",
    sortField: "ticket_number",
  },
  {
    id: "status",
    label: "Status",
    defaultVisible: true,
    className: "w-24 shrink-0",
    sortField: "status",
  },
  {
    id: "channel",
    label: "Channel",
    defaultVisible: true,
    className: "w-28 shrink-0",
    sortField: "channel",
  },
  {
    id: "priority",
    label: "Priority",
    defaultVisible: false,
    className: "w-28 shrink-0",
    sortField: "priority",
  },
  {
    id: "customer",
    label: "Customer / Last message",
    defaultVisible: true,
    className: "min-w-0 flex-1 overflow-hidden",
  },
  {
    id: "sla",
    label: "SLA",
    defaultVisible: true,
    className: "w-24 shrink-0",
    sortField: "sla_due_at",
  },
  {
    id: "assignee",
    label: "Assignee",
    defaultVisible: true,
    className: "w-32 shrink-0 truncate",
    sortField: "assignee",
  },
  {
    id: "updated",
    label: "Updated",
    defaultVisible: true,
    className: "w-20 shrink-0 text-right",
    sortField: "updated_at",
  },
];

export const TOGGLEABLE_QUEUE_COLUMNS: readonly QueueColumn[] =
  QUEUE_COLUMNS.filter((column) => column.id !== ALWAYS_VISIBLE_COLUMN_ID);

export const DEFAULT_VISIBLE_COLUMN_IDS: QueueColumnId[] =
  TOGGLEABLE_QUEUE_COLUMNS.filter((column) => column.defaultVisible).map(
    (column) => column.id,
  );

/**
 * Resolve stored column ids to columns in canonical order, whatever order the
 * user toggled them in.
 */
export function visibleQueueColumns(
  visibleIds: readonly string[],
): QueueColumn[] {
  const wanted = new Set(visibleIds);
  return QUEUE_COLUMNS.filter(
    (column) => column.id === ALWAYS_VISIBLE_COLUMN_ID || wanted.has(column.id),
  );
}

export interface QueueSort {
  field: QueueSortField;
  desc: boolean;
}

// Status has no meaningful natural order — use the lifecycle order instead.
const STATUS_ORDER: Record<string, number> = {
  new: 0,
  open: 1,
  pending: 2,
  on_hold: 3,
  resolved: 4,
};

/**
 * Ordering weight within a column sort. Deliberately identical to the ranking's
 * own scale: an untriaged ticket has *unknown* urgency, so it sorts above known
 * low priority rather than at the bottom of the list.
 */
function priorityWeight(priority: Ticket["priority"]): number {
  switch (priority) {
    case "high":
      return 3;
    case "medium":
      return 2;
    case "low":
      return 1;
    default:
      return 1.5;
  }
}

/**
 * A column sort is an *override* layered on the attention ranking, never a
 * replacement: `null` keeps the ranked order, and because the sort is stable
 * over an already-ranked list, rows that tie on the sorted column stay in
 * attention order.
 */
export function applyQueueSort(
  ranked: readonly ClassifiedTicket[],
  sort: QueueSort | null,
): ClassifiedTicket[] {
  if (!sort) return [...ranked];
  const direction = sort.desc ? -1 : 1;
  return [...ranked].sort((a, b) =>
    compareTickets(a.ticket, b.ticket, sort.field, direction),
  );
}

function compareTickets(
  a: Ticket,
  b: Ticket,
  field: QueueSortField,
  direction: number,
): number {
  switch (field) {
    case "ticket_number":
      return (a.ticket_number - b.ticket_number) * direction;
    case "status":
      return (
        ((STATUS_ORDER[a.status ?? "new"] ?? 0) -
          (STATUS_ORDER[b.status ?? "new"] ?? 0)) *
        direction
      );
    case "channel":
      return (
        channelLabel(a.channel_source).localeCompare(
          channelLabel(b.channel_source),
        ) * direction
      );
    case "priority":
      return (
        (priorityWeight(a.priority) - priorityWeight(b.priority)) * direction
      );
    case "sla_due_at": {
      const aDue = parseTime(a.sla_due_at);
      const bDue = parseTime(b.sla_due_at);
      // A ticket with no SLA carries no deadline signal at all; park those at
      // the end either way rather than letting a descending flip float them
      // above everything that genuinely has a deadline.
      if (aDue === null || bDue === null) {
        return aDue === bDue ? 0 : aDue === null ? 1 : -1;
      }
      return (aDue - bDue) * direction;
    }
    case "assignee": {
      const aAssignee = assigneeDisplay(a.assignee);
      const bAssignee = assigneeDisplay(b.assignee);
      // Same reasoning as the SLA column: unassigned is an absence, so it
      // stays at the bottom in both directions.
      if (aAssignee.kind === "unassigned" || bAssignee.kind === "unassigned") {
        return aAssignee.kind === bAssignee.kind
          ? 0
          : aAssignee.kind === "unassigned"
            ? 1
            : -1;
      }
      return (
        aAssignee.label.localeCompare(bAssignee.label, undefined, {
          sensitivity: "base",
        }) * direction
      );
    }
    case "updated_at":
      return (
        ((parseTime(a.updated_at) ?? 0) - (parseTime(b.updated_at) ?? 0)) *
        direction
      );
  }
}

export interface QueueFilters {
  status: string | null;
  priority: "low" | "medium" | "high" | null;
  channel: NonNullable<ListTicketsOptions["channelSource"]> | null;
  sla: NonNullable<ListTicketsOptions["sla"]> | null;
  assignee: "me" | "unassigned" | null;
  search: string;
}

export const EMPTY_QUEUE_FILTERS: QueueFilters = {
  status: null,
  priority: null,
  channel: null,
  sla: null,
  assignee: null,
  search: "",
};

const SLA_FILTER_LABELS: Record<string, string> = {
  breached: "Breached",
  "at-risk": "At risk",
  "on-track": "On track",
};

const ASSIGNEE_FILTER_LABELS: Record<string, string> = {
  me: "Me",
  unassigned: "Unassigned",
};

export interface QueueFilterChip {
  id: string;
  label: string;
  /** The filter set this chip's remove button produces. */
  next: QueueFilters;
}

/**
 * Every applied filter as an individually removable chip, so the filter state
 * is readable at a glance instead of hidden behind the Filters menu.
 */
export function queueFilterChips(filters: QueueFilters): QueueFilterChip[] {
  const chips: QueueFilterChip[] = [];
  if (filters.status) {
    chips.push({
      id: "status",
      label: `Status: ${statusLabel(filters.status)}`,
      next: { ...filters, status: null },
    });
  }
  if (filters.priority) {
    chips.push({
      id: "priority",
      label: `Priority: ${priorityLabel(filters.priority)}`,
      next: { ...filters, priority: null },
    });
  }
  if (filters.channel) {
    chips.push({
      id: "channel",
      label: `Channel: ${channelLabel(filters.channel)}`,
      next: { ...filters, channel: null },
    });
  }
  if (filters.sla) {
    chips.push({
      id: "sla",
      label: `SLA: ${SLA_FILTER_LABELS[filters.sla] ?? filters.sla}`,
      next: { ...filters, sla: null },
    });
  }
  if (filters.assignee) {
    chips.push({
      id: "assignee",
      label: `Assignee: ${ASSIGNEE_FILTER_LABELS[filters.assignee] ?? filters.assignee}`,
      next: { ...filters, assignee: null },
    });
  }
  const search = filters.search.trim();
  if (search) {
    chips.push({
      id: "search",
      label: `Search: ${search}`,
      next: { ...filters, search: "" },
    });
  }
  return chips;
}

/**
 * Translate the filter chips into list-endpoint options. `orderBy` stays
 * pinned regardless of the column sort: the queue re-orders the fetched page
 * client-side, so varying it would only churn the query key.
 */
export function queueListOptions(filters: QueueFilters): ListTicketsOptions {
  const options: ListTicketsOptions = { orderBy: "-updated_at" };
  if (filters.status) options.status = filters.status;
  if (filters.priority) options.priority = filters.priority;
  if (filters.channel) options.channelSource = filters.channel;
  if (filters.sla) options.sla = filters.sla;
  if (filters.assignee) options.assignee = filters.assignee;
  const search = filters.search.trim();
  if (search) options.search = search;
  return options;
}

export interface TicketActivityEntry {
  id: string;
  label: string;
  actor: string;
  at: string;
}

/**
 * The ticket's own timeline, derived from the thread we already load. PostHog's
 * activity log isn't reachable from the api-client yet, so this reports what
 * actually happened on the ticket rather than every field edit.
 */
export function ticketActivityEntries(
  ticket: Ticket,
  messages: readonly TicketMessage[] | undefined,
): TicketActivityEntry[] {
  const entries: TicketActivityEntry[] = [
    {
      id: "opened",
      label: `opened this ticket over ${channelLabel(ticket.channel_source)}`,
      actor: requesterLabel(ticket),
      at: ticket.created_at,
    },
  ];

  const latest = (predicate: (message: TicketMessage) => boolean) =>
    [...(messages ?? [])].reverse().find(predicate);

  const customerMessage = latest(
    (message) => message.author_type === "customer" && !message.is_private,
  );
  if (customerMessage) {
    entries.push({
      id: "customer-wrote",
      label: "wrote back",
      actor: customerMessage.author_name,
      at: customerMessage.created_at,
    });
  }

  const teamReply = latest(
    (message) => message.author_type !== "customer" && !message.is_private,
  );
  if (teamReply) {
    entries.push({
      id: "team-replied",
      label: "replied to the customer",
      actor: teamReply.author_name,
      at: teamReply.created_at,
    });
  }

  const note = latest((message) => message.is_private);
  if (note) {
    entries.push({
      id: "internal-note",
      label: "added an internal note",
      actor: note.author_name,
      at: note.created_at,
    });
  }

  return entries.sort(
    (a, b) => (parseTime(b.at) ?? 0) - (parseTime(a.at) ?? 0),
  );
}

/**
 * Identity the ticket belongs to, for grouping a customer's tickets together.
 * Falls back to the email envelope so unidentified email threads still group.
 */
export function requesterKey(ticket: Ticket): string | null {
  if (ticket.person?.id) return `person:${ticket.person.id}`;
  if (ticket.email_from) return `email:${ticket.email_from.toLowerCase()}`;
  return null;
}

export interface CustomerHistoryEntry {
  ticket: Ticket;
  isCurrent: boolean;
}

export interface CustomerHistory {
  entries: CustomerHistoryEntry[];
  /** Same-customer tickets beyond the display cap. */
  extra: number;
}

/**
 * This customer's other tickets, newest first, with the open one always
 * present so the card reads as their full history rather than a list the
 * current ticket is mysteriously missing from.
 */
export function customerTicketHistory(
  tickets: readonly Ticket[],
  current: Ticket,
  limit: number,
): CustomerHistory {
  const key = requesterKey(current);
  const sameCustomer = key
    ? tickets.filter((ticket) => requesterKey(ticket) === key)
    : [];
  const withCurrent = sameCustomer.some((ticket) => ticket.id === current.id)
    ? sameCustomer
    : [current, ...sameCustomer];
  const ordered = [...withCurrent].sort(
    (a, b) => (parseTime(b.updated_at) ?? 0) - (parseTime(a.updated_at) ?? 0),
  );
  return {
    entries: ordered.slice(0, limit).map((ticket) => ({
      ticket,
      isCurrent: ticket.id === current.id,
    })),
    extra: Math.max(0, ordered.length - limit),
  };
}

function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}
