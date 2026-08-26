import {
  activityActorLabel,
  summarizeActivity,
} from "@posthog/core/support/activitySummary";
import { Button, Text } from "@posthog/quill";
import { Section } from "@posthog/ui/features/support/components/TicketRailSection";
import { useSupportTicketActivity } from "@posthog/ui/features/support/hooks/useSupportTicketActivity";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { useState } from "react";

const COLLAPSED_COUNT = 5;

export function TicketActivity({ ticketId }: { ticketId: string }) {
  const { data, isPending, isError } = useSupportTicketActivity(ticketId);
  const [expanded, setExpanded] = useState(false);
  const entries = data ?? [];

  if (!isPending && !isError && entries.length === 0) {
    return null;
  }

  const shown = expanded ? entries : entries.slice(0, COLLAPSED_COUNT);
  const hidden = entries.length - shown.length;

  return (
    <Section title="Activity">
      <div className="flex flex-col gap-1 py-1.5">
        {isPending && (
          <Text className="text-[12px] text-muted-foreground">Loading…</Text>
        )}
        {isError && (
          <Text className="text-[12px] text-muted-foreground">
            Could not load activity.
          </Text>
        )}
        {shown.map((entry) => (
          <div key={entry.id} className="flex items-baseline gap-2">
            <Text className="min-w-0 flex-1 text-[12px] leading-snug">
              <span className="font-medium">{activityActorLabel(entry)}</span>{" "}
              <span className="text-muted-foreground">
                {summarizeActivity(entry)}
              </span>
            </Text>
            <RelativeTimestamp
              timestamp={entry.created_at}
              className="text-[10px] text-gray-11 tabular-nums"
            />
          </div>
        ))}
        {hidden > 0 && (
          <Button
            variant="default"
            size="sm"
            className="self-start px-0"
            onClick={() => setExpanded(true)}
          >
            {`Show ${hidden} more`}
          </Button>
        )}
        {expanded && entries.length > COLLAPSED_COUNT && (
          <Button
            variant="default"
            size="sm"
            className="self-start px-0"
            onClick={() => setExpanded(false)}
          >
            Show less
          </Button>
        )}
      </div>
    </Section>
  );
}
