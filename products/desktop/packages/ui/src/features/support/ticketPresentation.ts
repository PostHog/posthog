import type {
  Ticket,
  TicketAssignment,
} from "@posthog/api-client/posthog-client";

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

export function statusLabel(status: Ticket["status"]): string {
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

export type SlaState =
  | { kind: "none" }
  | { kind: "due"; dueAt: Date }
  | { kind: "breached"; dueAt: Date };

export function slaState(
  slaDueAt: string | null | undefined,
  now: Date,
): SlaState {
  if (!slaDueAt) return { kind: "none" };
  const dueAt = new Date(slaDueAt);
  if (Number.isNaN(dueAt.getTime())) return { kind: "none" };
  return dueAt.getTime() < now.getTime()
    ? { kind: "breached", dueAt }
    : { kind: "due", dueAt };
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
