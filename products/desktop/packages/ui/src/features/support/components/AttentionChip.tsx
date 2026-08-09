import type { Ticket } from "@posthog/api-client/posthog-client";
import type { AttentionState } from "@posthog/core/support/attention";
import { Badge } from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";

/**
 * The "why is this here" chip on every queue row — an unexplained ranking
 * won't be trusted, and an untrusted ranking gets ignored (plan principle 2).
 */
export function AttentionChip({
  state,
  ticket,
}: {
  state: AttentionState;
  ticket: Ticket;
}) {
  switch (state) {
    case "sla-breached":
      return (
        <Badge className="shrink-0" variant="destructive">
          SLA breached
        </Badge>
      );
    case "customer-replied":
      return (
        <Badge className="shrink-0" variant="info">
          Customer replied{" "}
          <RelativeTimestamp timestamp={ticket.last_message_at} />
        </Badge>
      );
    case "agent-handed-back":
      return (
        <Badge className="shrink-0" variant="info">
          Agent handed back
        </Badge>
      );
    case "sla-at-risk":
      return (
        <Badge className="shrink-0" variant="warning">
          SLA <RelativeTimestamp timestamp={ticket.sla_due_at} />
        </Badge>
      );
    case "snooze-elapsed":
      return (
        <Badge className="shrink-0" variant="warning">
          Snooze elapsed
        </Badge>
      );
    case "untriaged":
      return (
        <Badge className="shrink-0" variant="warning">
          Needs triage
        </Badge>
      );
    case "in-progress":
      return (
        <Badge className="shrink-0" variant="default">
          In progress
        </Badge>
      );
    case "waiting-on-customer":
      return (
        <Badge className="shrink-0" variant="default">
          Waiting on customer
        </Badge>
      );
    case "snoozed":
      return (
        <Badge className="shrink-0" variant="default">
          Snoozed
        </Badge>
      );
  }
}
