import { XIcon } from "@phosphor-icons/react";
import { type QueueFilters, queueFilterChips } from "../ticketPresentation";

/**
 * Applied filters as individually removable chips. Filter state stays on
 * screen rather than hiding behind the Filters menu, so it's obvious when the
 * queue you're looking at isn't the whole queue.
 */
export function QueueFilterChips({
  filters,
  onChange,
  onClearAll,
}: {
  filters: QueueFilters;
  onChange: (next: QueueFilters) => void;
  onClearAll: () => void;
}) {
  const chips = queueFilterChips(filters);
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
