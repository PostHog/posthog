import type { SupportActivityEntry } from "@posthog/api-client/posthog-client";
import { groupActivity } from "@posthog/core/support/activityGroups";
import {
  activityActorLabel,
  summarizeActivity,
} from "@posthog/core/support/activitySummary";
import { Button, cn, Text } from "@posthog/quill";
import { Section } from "@posthog/ui/features/support/components/TicketRailSection";
import { useSupportTicketActivity } from "@posthog/ui/features/support/hooks/useSupportTicketActivity";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { useState } from "react";

const COLLAPSED_COUNT = 5;

/**
 * The rail node beside an activity row: hollow for a lone entry, filled when
 * the entry arrived as part of a burst, with `connect` drawing a segment down
 * toward the next node so the burst reads as one run. The row's container
 * must be `position: relative`.
 */
function RailMark({
  grouped = false,
  connect = false,
}: {
  grouped?: boolean;
  connect?: boolean;
}) {
  return (
    <>
      <span
        aria-hidden
        className={cn(
          "-left-2.5 pointer-events-none absolute top-[7px] size-[5px] rounded-full border-[1.5px] border-muted-foreground",
          grouped ? "bg-muted-foreground" : "bg-card",
        )}
      />
      {connect && (
        <span
          aria-hidden
          className="-left-2 -bottom-1.5 pointer-events-none absolute top-[13px] w-px bg-border"
        />
      )}
    </>
  );
}

function ActivityRow({
  entry,
  grouped = false,
  connect = false,
}: {
  entry: SupportActivityEntry;
  grouped?: boolean;
  connect?: boolean;
}) {
  return (
    <li className="relative flex items-baseline gap-2">
      <RailMark grouped={grouped} connect={connect} />
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
    </li>
  );
}

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
        <ul className="flex flex-col gap-1 pl-4">
          {groupActivity(shown).map((group) =>
            group.entries.length === 1 ? (
              <ActivityRow key={group.key} entry={group.entries[0]} />
            ) : (
              <li key={group.key}>
                <ul className="flex flex-col gap-1">
                  {group.entries.map((groupEntry, index) => (
                    <ActivityRow
                      key={groupEntry.id}
                      entry={groupEntry}
                      grouped
                      connect={index < group.entries.length - 1}
                    />
                  ))}
                </ul>
              </li>
            ),
          )}
        </ul>
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
