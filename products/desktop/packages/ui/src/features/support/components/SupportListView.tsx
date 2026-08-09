import {
  ArrowDownIcon,
  ArrowsDownUpIcon,
  ArrowUpIcon,
  LifebuoyIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import { rankQueue } from "@posthog/core/support/attention";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Input,
  Spinner,
} from "@posthog/quill";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToSupportTicketDetail } from "@posthog/ui/router/navigationBridge";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useSupportTickets } from "../hooks/useSupportTickets";
import { useSupportTicketViews } from "../hooks/useSupportTicketViews";
import { useSupportQueueStore } from "../supportQueueStore";
import {
  applyQueueSort,
  EMPTY_QUEUE_FILTERS,
  isUnknownSavedViewError,
  type QueueColumn,
  type QueueFilters,
  type QueueSort,
  type QueueSortField,
  queueListOptions,
  visibleQueueColumns,
} from "../ticketPresentation";
import { QueueDisplayMenu } from "./QueueDisplayMenu";
import { QueueFilterChips } from "./QueueFilterChips";
import { QueueFilterMenu } from "./QueueFilterMenu";
import { QueueViewPicker } from "./QueueViewPicker";
import { SectionLabel } from "./SectionLabel";
import { TicketRow } from "./TicketRow";

// Long enough that a typed word costs one request, short enough to feel live.
const SEARCH_DEBOUNCE_MS = 300;

/**
 * The attention queue: tickets ranked by what needs attention now, every row
 * carrying the reason for its rank. Ranking is pure core logic
 * (@posthog/core/support/attention); a column sort layers on top of it as an
 * explicit, resettable override.
 */
export function SupportListView() {
  const [filters, setFilters] = useState<QueueFilters>(EMPTY_QUEUE_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const sort = useSupportQueueStore((state) => state.sort);
  const toggleSort = useSupportQueueStore((state) => state.toggleSort);
  const clearSort = useSupportQueueStore((state) => state.clearSort);
  const visibleColumnIds = useSupportQueueStore(
    (state) => state.visibleColumnIds,
  );
  const columns = useMemo(
    () => visibleQueueColumns(visibleColumnIds),
    [visibleColumnIds],
  );

  // Typing stays instant; only the settled term reaches the query key, so a
  // burst of keystrokes is one request rather than one per character.
  useEffect(() => {
    const timer = setTimeout(
      () => setFilters((current) => ({ ...current, search: searchInput })),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [searchInput]);

  const views = useSupportTicketViews();
  const { data, isPending, isError, error } = useSupportTickets(
    queueListOptions(filters),
  );

  // A view deleted or renamed elsewhere 400s on the next poll, which would
  // otherwise park the queue on an error the user can't clear from here. Drop
  // the view and say so — the retry runs unscoped and lands on all tickets.
  // Guarded on `filters.view`, so clearing it also stops this firing again.
  useEffect(() => {
    if (!filters.view || !isUnknownSavedViewError(error)) return;
    setFilters((current) => ({ ...current, view: null }));
    toast.info("That saved view no longer exists", {
      description: "Showing all tickets instead.",
      id: "support-stale-view",
    });
  }, [error, filters.view]);

  // One clock per data refresh, shared by the ranking and every row's SLA
  // stripe, so no two rows disagree about "now" and the order stays stable
  // between renders.
  const { now, rows } = useMemo(() => {
    const at = new Date();
    return {
      now: at,
      rows: applyQueueSort(rankQueue(data?.results ?? [], at), sort),
    };
  }, [data, sort]);

  const applyFilters = (next: QueueFilters) => {
    setFilters(next);
    setSearchInput(next.search);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pt-4 pb-3">
        <h2 className="font-semibold text-[18px]">Support</h2>
        <QueueViewPicker
          views={views.data}
          isPending={views.isPending}
          isError={views.isError}
          activeShortId={filters.view}
          onChange={(view) => applyFilters({ ...filters, view })}
        />
        <QueueFilterMenu filters={filters} onChange={applyFilters} />
        <QueueDisplayMenu />
        <div className="relative ml-auto">
          <MagnifyingGlassIcon
            size={14}
            className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2.5 text-muted-foreground"
          />
          <Input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search tickets…"
            aria-label="Search tickets"
            maxLength={200}
            className="w-64 pl-8"
          />
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pb-2">
        <QueueFilterChips
          filters={filters}
          views={views.data}
          onChange={applyFilters}
          onClearAll={() => applyFilters(EMPTY_QUEUE_FILTERS)}
        />
        {sort && (
          <button
            type="button"
            onClick={clearSort}
            className="ml-auto cursor-pointer text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Sorted by column — back to attention order
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
        <div className="overflow-hidden rounded-lg border border-border">
          <ListHeader columns={columns} sort={sort} onToggle={toggleSort} />
          {isPending && (
            <QueueState>
              <EmptyMedia variant="icon">
                <Spinner />
              </EmptyMedia>
              <EmptyTitle>Loading tickets</EmptyTitle>
            </QueueState>
          )}
          {isError && (
            <QueueState>
              <EmptyMedia variant="icon">
                <LifebuoyIcon size={20} />
              </EmptyMedia>
              <EmptyTitle>Couldn't load tickets</EmptyTitle>
              <EmptyDescription>
                Check that Conversations is enabled for this project, then try
                again.
              </EmptyDescription>
            </QueueState>
          )}
          {!isPending && !isError && rows.length === 0 && (
            <QueueState>
              <EmptyMedia variant="icon">
                <LifebuoyIcon size={20} />
              </EmptyMedia>
              <EmptyTitle>No tickets</EmptyTitle>
              <EmptyDescription>
                Customer tickets from Conversations will show up here.
              </EmptyDescription>
            </QueueState>
          )}
          {rows.length > 0 && (
            <ul className="divide-y divide-border">
              {rows.map(({ ticket, state }) => (
                <TicketRow
                  key={ticket.id}
                  ticket={ticket}
                  state={state}
                  columns={columns}
                  now={now}
                  onClick={() => navigateToSupportTicketDetail(ticket.id)}
                />
              ))}
            </ul>
          )}
        </div>
        {data && (
          <div className="pt-2 text-[11px] text-muted-foreground">
            {rows.length === 0
              ? "No tickets need attention"
              : `${rows.length} of ${data.count} tickets need attention`}
          </div>
        )}
      </div>
    </div>
  );
}

function QueueState({ children }: { children: ReactNode }) {
  return (
    <Empty className="border-0 bg-card py-8">
      <EmptyHeader>{children}</EmptyHeader>
    </Empty>
  );
}

function ListHeader({
  columns,
  sort,
  onToggle,
}: {
  columns: readonly QueueColumn[];
  sort: QueueSort | null;
  onToggle: (field: QueueSortField) => void;
}) {
  return (
    <div className="flex items-center border-border border-b bg-muted/50">
      {/* Matches each row's SLA stripe so header and cells line up. */}
      <span aria-hidden className="w-1 shrink-0" />
      <SectionLabel
        size="xs"
        className="flex flex-1 items-center gap-3 py-2 pr-4 pl-3"
      >
        {columns.map((column) =>
          column.sortField ? (
            <SortHeader
              key={column.id}
              column={column}
              sort={sort}
              onToggle={onToggle}
            />
          ) : (
            <div key={column.id} className={column.className}>
              {column.label}
            </div>
          ),
        )}
      </SectionLabel>
    </div>
  );
}

function SortHeader({
  column,
  sort,
  onToggle,
}: {
  column: QueueColumn;
  sort: QueueSort | null;
  onToggle: (field: QueueSortField) => void;
}) {
  const field = column.sortField as QueueSortField;
  const isActive = sort?.field === field;
  const SortIcon = !isActive
    ? ArrowsDownUpIcon
    : sort.desc
      ? ArrowDownIcon
      : ArrowUpIcon;
  return (
    <button
      type="button"
      onClick={() => onToggle(field)}
      className={`inline-flex cursor-pointer items-center gap-1 hover:text-foreground ${
        isActive ? "text-foreground" : ""
      } ${column.className} ${column.id === "updated" ? "justify-end" : ""}`}
    >
      <span>{column.label}</span>
      <SortIcon size={10} />
    </button>
  );
}
