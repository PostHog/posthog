import type { Schemas } from "@posthog/api-client";
import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import type {
  TicketAttention,
  TicketSlaState,
} from "@posthog/core/support/ticketState";

export const TICKET_STATUS_LABELS: Record<Schemas.TicketStatusEnum, string> = {
  new: "New",
  open: "Open",
  pending: "Pending",
  on_hold: "On hold",
  resolved: "Resolved",
};

export const TICKET_PRIORITY_LABELS: Record<Schemas.PriorityEnum, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

export const TICKET_ATTENTION_LABELS: Record<TicketAttention, string> = {
  "customer-replied": "Customer replied",
  "sla-breached": "SLA overdue",
  "sla-at-risk": "SLA soon",
  untriaged: "Untriaged",
  snoozed: "Snoozed",
  "waiting-on-customer": "Waiting on customer",
  "in-progress": "In progress",
  resolved: "Resolved",
};

type BadgeVariant =
  | "default"
  | "info"
  | "success"
  | "warning"
  | "destructive"
  | "completed";

export const TICKET_STATUS_VARIANTS: Record<
  Schemas.TicketStatusEnum,
  BadgeVariant
> = {
  new: "info",
  open: "success",
  pending: "warning",
  on_hold: "warning",
  resolved: "completed",
};

/** Null priority is untriaged, not low, so it reads as absent rather than calm. */
export const TICKET_PRIORITY_VARIANTS: Record<
  Schemas.PriorityEnum,
  BadgeVariant
> = {
  low: "default",
  medium: "warning",
  high: "destructive",
};

export const TICKET_ATTENTION_VARIANTS: Record<TicketAttention, BadgeVariant> =
  {
    "customer-replied": "info",
    "sla-breached": "destructive",
    "sla-at-risk": "warning",
    untriaged: "default",
    snoozed: "default",
    "waiting-on-customer": "default",
    "in-progress": "default",
    resolved: "completed",
  };

export const SLA_TEXT_CLASSES: Record<TicketSlaState, string> = {
  none: "text-muted-foreground",
  "on-track": "text-muted-foreground",
  "at-risk": "text-(--amber-11)",
  breached: "text-(--red-11)",
};

export function ticketStatusLabel(
  status: Schemas.TicketStatusEnum | undefined,
): string {
  return status ? TICKET_STATUS_LABELS[status] : TICKET_STATUS_LABELS.new;
}

export function ticketPriorityLabel(
  priority: SupportTicket["priority"],
): string {
  return priority ? TICKET_PRIORITY_LABELS[priority] : "No priority";
}

/** The person a ticket is from, falling back through what the channel supplied. */
export function ticketRequesterName(ticket: SupportTicket): string {
  const traits = ticket.anonymous_traits as
    | { name?: string; email?: string }
    | null
    | undefined;

  return (
    ticket.person?.name ||
    traits?.name ||
    traits?.email ||
    ticket.email_from ||
    "Unknown requester"
  );
}

export function ticketAssigneeName(ticket: SupportTicket): string {
  const assignee = ticket.assignee;
  if (!assignee) {
    return "Unassigned";
  }
  const user = assignee.user as
    | { first_name?: string; email?: string }
    | null
    | undefined;
  if (user) {
    return user.first_name || user.email || "Assigned";
  }
  const role = assignee.role as { name?: string } | null | undefined;
  return role?.name ? `${role.name} (pool)` : "Assigned";
}

/** Team-authored rows sit on the right; the customer and the agent on the left. */
export function isTeamAuthoredMessage(message: SupportTicketMessage): boolean {
  return message.author_type === "support";
}

export function messageAuthorLabel(message: SupportTicketMessage): string {
  if (message.author_type === "AI") {
    return message.author_name || "PostHog AI";
  }
  return message.author_name || "Unknown";
}

/**
 * A short relative age for list rows and message headers. Anything past a week
 * reads better as a date than as a growing pile of days.
 */
export function formatTicketAge(
  timestamp: string | null | undefined,
  now: number,
): string {
  if (!timestamp) {
    return "";
  }
  const parsed = Date.parse(timestamp);
  if (Number.isNaN(parsed)) {
    return "";
  }

  const elapsedMs = Math.max(0, now - parsed);
  const minutes = Math.floor(elapsedMs / 60_000);
  if (minutes < 1) {
    return "now";
  }
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h`;
  }
  const days = Math.floor(hours / 24);
  if (days < 7) {
    return `${days}d`;
  }
  return new Date(parsed).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
}

/** A countdown for an SLA chip: "in 3h" while there is time, "2h overdue" after. */
export function formatSlaCountdown(
  slaDueAt: string | null | undefined,
  now: number,
): string | null {
  if (!slaDueAt) {
    return null;
  }
  const dueAt = Date.parse(slaDueAt);
  if (Number.isNaN(dueAt)) {
    return null;
  }

  const deltaMs = Math.abs(dueAt - now);
  const minutes = Math.max(1, Math.round(deltaMs / 60_000));
  const span =
    minutes < 60
      ? `${minutes}m`
      : minutes < 60 * 24
        ? `${Math.round(minutes / 60)}h`
        : `${Math.round(minutes / (60 * 24))}d`;

  return dueAt >= now ? `SLA in ${span}` : `SLA ${span} overdue`;
}
