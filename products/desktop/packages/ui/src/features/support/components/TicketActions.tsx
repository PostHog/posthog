import { AlarmIcon } from "@phosphor-icons/react";
import type { Ticket, TicketUpdate } from "@posthog/api-client/posthog-client";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@posthog/quill";
import { toast } from "@posthog/ui/primitives/toast";
import { useUpdateSupportTicket } from "../hooks/useUpdateSupportTicket";
import { snoozePresets } from "../ticketPresentation";

const STATUS_OPTIONS: Array<{
  value: NonNullable<Ticket["status"]>;
  label: string;
}> = [
  { value: "new", label: "New" },
  { value: "open", label: "Open" },
  { value: "pending", label: "Pending" },
  { value: "on_hold", label: "On hold" },
  { value: "resolved", label: "Resolved" },
];

// Null is a real option: clearing priority returns the ticket to untriaged.
const PRIORITY_OPTIONS: Array<{
  value: "low" | "medium" | "high" | null;
  label: string;
}> = [
  { value: null, label: "No priority" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

/**
 * Triage controls for a ticket: status, priority, snooze. Every attention
 * state the queue surfaces has its verb here — a queue that ranks work you
 * can't act on is just an anxiety feed.
 */
export function TicketActions({ ticket }: { ticket: Ticket }) {
  const updateTicket = useUpdateSupportTicket(ticket.id);
  const update = (updates: TicketUpdate) =>
    updateTicket.mutate(updates, {
      onError: () => toast.error("Couldn't update the ticket"),
    });

  const priorityValue =
    ticket.priority === "low" ||
    ticket.priority === "medium" ||
    ticket.priority === "high"
      ? ticket.priority
      : null;

  return (
    <div className="flex items-center gap-2">
      <Select
        value={ticket.status ?? "new"}
        onValueChange={(status: string | null) => {
          if (status) update({ status: status as TicketUpdate["status"] });
        }}
        disabled={updateTicket.isPending}
        items={STATUS_OPTIONS}
      >
        <SelectTrigger size="sm" aria-label="Ticket status">
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start" side="bottom" sideOffset={6}>
          {STATUS_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={priorityValue}
        onValueChange={(priority: string | null) =>
          update({ priority: priority as TicketUpdate["priority"] })
        }
        disabled={updateTicket.isPending}
        items={PRIORITY_OPTIONS}
      >
        <SelectTrigger size="sm" aria-label="Ticket priority">
          <SelectValue placeholder="No priority" />
        </SelectTrigger>
        <SelectContent align="start" side="bottom" sideOffset={6}>
          {PRIORITY_OPTIONS.map((option) => (
            <SelectItem key={option.value ?? "none"} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              type="button"
              size="sm"
              aria-label="Snooze ticket"
              disabled={updateTicket.isPending}
            >
              <AlarmIcon size={14} />
              {ticket.snoozed_until ? "Snoozed" : "Snooze"}
            </Button>
          }
        />
        <DropdownMenuContent align="start" side="bottom" sideOffset={6}>
          {snoozePresets(new Date()).map((preset) => (
            <DropdownMenuItem
              key={preset.id}
              onClick={() =>
                update({ snoozed_until: preset.until.toISOString() })
              }
            >
              {preset.label}
            </DropdownMenuItem>
          ))}
          {ticket.snoozed_until && (
            <DropdownMenuItem onClick={() => update({ snoozed_until: null })}>
              Unsnooze
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
