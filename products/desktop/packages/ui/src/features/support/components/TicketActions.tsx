import { MoonIcon } from "@phosphor-icons/react";
import type { Ticket, TicketUpdate } from "@posthog/api-client/posthog-client";
import { toast } from "@posthog/ui/primitives/toast";
import { useUpdateSupportTicket } from "../hooks/useUpdateSupportTicket";
import {
  assigneeDisplay,
  PRIORITY_PILL_CLASS,
  priorityLabel,
  STATUS_PILL_CLASS,
  snoozePresets,
  statusLabel,
} from "../ticketPresentation";
import { PillPicker } from "./PillPicker";
import { CardPickerRow, CardRow } from "./SidebarCard";

const STATUS_OPTIONS: Array<NonNullable<Ticket["status"]>> = [
  "new",
  "open",
  "pending",
  "on_hold",
  "resolved",
];

// Null is a real option: clearing priority returns the ticket to untriaged.
const PRIORITY_OPTIONS: Array<"low" | "medium" | "high" | null> = [
  null,
  "low",
  "medium",
  "high",
];

const STATUS_DOT_CLASS: Record<string, string> = {
  new: "bg-info-foreground",
  open: "bg-warning-foreground",
  pending: "bg-muted-foreground",
  on_hold: "bg-muted-foreground",
  resolved: "bg-success-foreground",
};

const PRIORITY_DOT_CLASS: Record<string, string> = {
  low: "bg-muted-foreground",
  medium: "bg-warning-foreground",
  high: "bg-destructive-foreground",
  none: "bg-warning-foreground",
};

/**
 * Triage controls for a ticket: status, priority, snooze. Every attention
 * state the queue surfaces has its verb here — a queue that ranks work you
 * can't act on is just an anxiety feed.
 *
 * Assignee is a read-only row: the ticket serializer refuses assignment
 * writes, so a picker here would imply a capability we don't have.
 */
export function TicketActions({ ticket }: { ticket: Ticket }) {
  const updateTicket = useUpdateSupportTicket(ticket.id);
  const update = (updates: TicketUpdate) =>
    updateTicket.mutate(updates, {
      onError: () => toast.error("Couldn't update the ticket"),
    });

  const status = ticket.status ?? "new";
  const priorityKey = ticket.priority ?? "none";
  const assignee = assigneeDisplay(ticket.assignee);
  const isSnoozed = Boolean(ticket.snoozed_until);

  return (
    <div className="space-y-1.5">
      <CardPickerRow label="Status">
        <PillPicker
          ariaLabel="Ticket status"
          label={statusLabel(ticket.status)}
          className={STATUS_PILL_CLASS[status] ?? "bg-muted text-foreground"}
          disabled={updateTicket.isPending}
          items={STATUS_OPTIONS.map((option) => ({
            id: option,
            label: statusLabel(option),
            dotClass: STATUS_DOT_CLASS[option],
            current: option === status,
            onSelect: () =>
              update({ status: option as TicketUpdate["status"] }),
          }))}
        />
      </CardPickerRow>
      <CardPickerRow label="Priority">
        <PillPicker
          ariaLabel="Ticket priority"
          label={priorityLabel(ticket.priority)}
          className={
            PRIORITY_PILL_CLASS[priorityKey] ?? PRIORITY_PILL_CLASS.none
          }
          disabled={updateTicket.isPending}
          items={PRIORITY_OPTIONS.map((option) => ({
            id: option ?? "none",
            label: priorityLabel(option),
            dotClass: PRIORITY_DOT_CLASS[option ?? "none"],
            current: (ticket.priority ?? null) === option,
            onSelect: () =>
              update({ priority: option as TicketUpdate["priority"] }),
          }))}
        />
      </CardPickerRow>
      <CardPickerRow label="Snooze">
        <PillPicker
          ariaLabel="Snooze ticket"
          label={isSnoozed ? "Snoozed" : "Snooze"}
          icon={isSnoozed ? <MoonIcon size={11} /> : undefined}
          className={
            isSnoozed
              ? "bg-warning text-warning-foreground"
              : "bg-muted text-muted-foreground"
          }
          disabled={updateTicket.isPending}
          items={[
            ...snoozePresets(new Date()).map((preset) => ({
              id: preset.id,
              label: preset.label,
              onSelect: () =>
                update({ snoozed_until: preset.until.toISOString() }),
            })),
            ...(isSnoozed
              ? [
                  {
                    id: "unsnooze",
                    label: "Unsnooze",
                    onSelect: () => update({ snoozed_until: null }),
                  },
                ]
              : []),
          ]}
        />
      </CardPickerRow>
      <CardRow
        label="Assignee"
        value={
          assignee.kind === "role" ? `${assignee.label} (pool)` : assignee.label
        }
      />
      <CardRow
        label="Snoozed until"
        value={
          ticket.snoozed_until
            ? new Date(ticket.snoozed_until).toLocaleString()
            : null
        }
      />
    </div>
  );
}
