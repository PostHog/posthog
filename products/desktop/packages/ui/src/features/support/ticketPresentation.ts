import type { Schemas } from "@posthog/api-client";
import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import type { TicketSlaState } from "@posthog/core/support/ticketState";

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

export const TICKET_PRIORITY_VARIANTS: Record<
  Schemas.PriorityEnum,
  BadgeVariant
> = {
  low: "default",
  medium: "warning",
  high: "destructive",
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
  return TICKET_STATUS_LABELS[status ?? "new"];
}

export function ticketPriorityLabel(
  priority: SupportTicket["priority"],
): string {
  return priority ? TICKET_PRIORITY_LABELS[priority] : "No priority";
}

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
  const roleName = assignee.role?.name;
  return assignee.user?.email ?? (roleName ? `${roleName} (pool)` : "Assigned");
}

export function messageAuthorLabel(message: SupportTicketMessage): string {
  return message.author_name || "Unknown";
}

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

  const minutes = Math.max(1, Math.round(Math.abs(dueAt - now) / 60_000));
  const span =
    minutes < 60
      ? `${minutes}m`
      : minutes < 60 * 24
        ? `${Math.round(minutes / 60)}h`
        : `${Math.round(minutes / (60 * 24))}d`;

  return dueAt >= now ? `SLA in ${span}` : `SLA ${span} overdue`;
}
