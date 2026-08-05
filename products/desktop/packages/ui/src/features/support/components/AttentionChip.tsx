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
      return <Badge variant="destructive">SLA breached</Badge>;
    case "customer-replied":
      return (
        <Badge variant="info">
          Customer replied{" "}
          <RelativeTimestamp timestamp={ticket.last_message_at} />
        </Badge>
      );
    case "agent-handed-back":
      return <Badge variant="info">Agent handed back</Badge>;
    case "sla-at-risk":
      return (
        <Badge variant="warning">
          SLA <RelativeTimestamp timestamp={ticket.sla_due_at} />
        </Badge>
      );
    case "snooze-elapsed":
      return <Badge variant="warning">Snooze elapsed</Badge>;
    case "untriaged":
      return <Badge variant="warning">Needs triage</Badge>;
    case "in-progress":
      return <Badge variant="default">In progress</Badge>;
    case "waiting-on-customer":
      return <Badge variant="default">Waiting on customer</Badge>;
    case "snoozed":
      return <Badge variant="default">Snoozed</Badge>;
  }
}
