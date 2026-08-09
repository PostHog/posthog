import { XIcon } from "@phosphor-icons/react";
import type { TicketView } from "@posthog/api-client/posthog-client";
import { type QueueFilters, queueFilterChips } from "../ticketPresentation";

/**
 * Everything narrowing the queue right now — the applied saved view and each
 * filter — as individually removable chips. Showing them as peers is what
 * makes it readable that filters refine a view rather than replace it.
 */
export function QueueFilterChips({
  filters,
  views,
  onChange,
  onClearAll,
}: {
  filters: QueueFilters;
  /** Supplies the applied view's display name; the chip renders either way. */
  views: TicketView[] | undefined;
  onChange: (next: QueueFilters) => void;
  onClearAll: () => void;
}) {
  const chips = queueFilterChips(filters, views);
  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((chip) => (
        <span
          key={chip.id}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-card py-0.5 pr-1 pl-2.5 text-[11px] text-foreground"
        >
          <span className="max-w-52 truncate">{chip.label}</span>
          <button
            type="button"
            onClick={() => onChange(chip.next)}
            aria-label={`Remove filter ${chip.label}`}
            className="cursor-pointer rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <XIcon size={10} />
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={onClearAll}
        className="cursor-pointer text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
      >
        Clear all
      </button>
    </div>
  );
}
