import { CaretDownIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import type {
  SupportAssigneeFilter,
  SupportTicket,
  SupportTicketListOptions,
  SupportTicketOrderBy,
} from "@posthog/api-client/posthog-client";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  MenuLabel,
  Spinner,
  Text,
} from "@posthog/quill";
import { TicketRow } from "@posthog/ui/features/support/components/TicketRow";
import { useSupportTicketsInfinite } from "@posthog/ui/features/support/hooks/useSupportTickets";
import { useSupportTicketViews } from "@posthog/ui/features/support/hooks/useSupportTicketViews";
import {
  sortedPinnedTicketIds,
  usePinnedTicketsStore,
} from "@posthog/ui/features/support/pinnedTicketsStore";
import { supportTicketQuery } from "@posthog/ui/features/support/supportQueries";
import {
  QUEUE_STATUSES,
  type SupportAssigneeScope,
  useSupportQueueStore,
} from "@posthog/ui/features/support/supportQueueStore";
import { useDebounce } from "@posthog/ui/primitives/hooks/useDebounce";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { navigateToSupportTicket } from "@posthog/ui/router/navigationBridge";
import { useQueries } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

const SCOPE_LABELS: Record<SupportAssigneeScope, string> = {
  me: "My tickets",
  unassigned: "Unassigned",
  all: "All tickets",
};

const SEARCH_DEBOUNCE_MS = 300;

function assigneeFilterFor(
  scope: SupportAssigneeScope,
): SupportAssigneeFilter[] | undefined {
  if (scope === "me") {
    return ["me"];
  }
  if (scope === "unassigned") {
    return ["unassigned"];
  }
  return undefined;
}

export function TicketList({ activeTicketId }: { activeTicketId?: string }) {
  const assigneeScope = useSupportQueueStore((state) => state.assigneeScope);
  const orderBy = useSupportQueueStore((state) => state.orderBy);
  const search = useSupportQueueStore((state) => state.search);
  const viewShortId = useSupportQueueStore((state) => state.viewShortId);
  const { setAssigneeScope, setOrderBy, setSearch, setViewShortId } =
    useSupportQueueStore.getState();

  const debouncedSearch = useDebounce(search, SEARCH_DEBOUNCE_MS);
  const { data: views } = useSupportTicketViews();

  const listOptions = useMemo<SupportTicketListOptions>(
    () => ({
      assignee: assigneeFilterFor(assigneeScope),
      status: QUEUE_STATUSES,
      orderBy,
      search: debouncedSearch.trim() || undefined,
      view: viewShortId ?? undefined,
    }),
    [assigneeScope, orderBy, debouncedSearch, viewShortId],
  );

  const {
    tickets,
    isPending,
    isError,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useSupportTicketsInfinite(listOptions);

  const pinnedAtById = usePinnedTicketsStore((state) => state.pinnedAtById);
  const pinnedIds = useMemo(
    () => sortedPinnedTicketIds(pinnedAtById),
    [pinnedAtById],
  );
  const showPinnedSection =
    assigneeScope === "me" &&
    viewShortId === null &&
    debouncedSearch.trim() === "" &&
    pinnedIds.length > 0;
  const pinnedQueries = useQueries({
    queries: pinnedIds.map((id) => ({
      ...supportTicketQuery(id),
      enabled: showPinnedSection,
    })),
  });
  const pinnedTickets = showPinnedSection
    ? pinnedQueries
        .map((query) => query.data)
        .filter((ticket): ticket is SupportTicket => ticket !== undefined)
    : [];
  const unpinnedTickets = showPinnedSection
    ? tickets.filter((ticket) => pinnedAtById[ticket.id] === undefined)
    : tickets;

  const [loadMoreRef, loadMoreInView] = useInView();
  useEffect(() => {
    if (loadMoreInView && hasNextPage && !isFetchingNextPage) {
      void fetchNextPage({ cancelRefetch: false });
    }
  }, [loadMoreInView, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const activeView = views?.find((view) => view.short_id === viewShortId);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-col gap-2 p-2">
        <div className="flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="default" size="sm">
                  {activeView?.name ?? SCOPE_LABELS[assigneeScope]}
                  <CaretDownIcon size={10} weight="bold" />
                </Button>
              }
            />
            <DropdownMenuContent align="start" className="min-w-56">
              <DropdownMenuRadioGroup
                value={viewShortId ? "" : assigneeScope}
                onValueChange={(value) => {
                  setViewShortId(null);
                  setAssigneeScope(value as SupportAssigneeScope);
                }}
              >
                {(Object.keys(SCOPE_LABELS) as SupportAssigneeScope[]).map(
                  (scope) => (
                    <DropdownMenuRadioItem key={scope} value={scope}>
                      {SCOPE_LABELS[scope]}
                    </DropdownMenuRadioItem>
                  ),
                )}
              </DropdownMenuRadioGroup>
              {views && views.length > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>Saved views</DropdownMenuLabel>
                    {views.map((view) => (
                      <DropdownMenuItem
                        key={view.short_id}
                        onClick={() => setViewShortId(view.short_id)}
                      >
                        {view.name}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuGroup>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="default" size="sm" className="ml-auto">
                  Sort
                  <CaretDownIcon size={10} weight="bold" />
                </Button>
              }
            />
            <DropdownMenuContent align="end" className="min-w-48">
              <DropdownMenuRadioGroup
                value={orderBy}
                onValueChange={(value) =>
                  setOrderBy(value as SupportTicketOrderBy)
                }
              >
                <DropdownMenuRadioItem value="-updated_at">
                  Recently updated
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="-created_at">
                  Newest
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="sla_due_at">
                  SLA deadline
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <InputGroup className="h-7">
          <InputGroupAddon>
            <MagnifyingGlassIcon size={14} />
          </InputGroupAddon>
          <InputGroupInput
            value={search}
            placeholder="Search tickets…"
            onChange={(event) => setSearch(event.target.value)}
          />
        </InputGroup>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-2">
        {isPending && (
          <div className="flex justify-center p-4">
            <Spinner className="size-4 text-gray-9" />
          </div>
        )}

        {isError && !isPending && (
          <Text className="block p-3 text-[13px] text-muted-foreground">
            Could not load tickets. They will reappear when the connection
            recovers.
          </Text>
        )}

        {!isPending &&
          !isError &&
          tickets.length === 0 &&
          pinnedTickets.length === 0 && (
            <Empty className="p-4">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <MagnifyingGlassIcon size={18} />
                </EmptyMedia>
                <EmptyTitle>No tickets here</EmptyTitle>
                <EmptyDescription>
                  Nothing matches this queue right now.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

        {showPinnedSection && pinnedTickets.length > 0 && (
          <>
            <MenuLabel className="flex items-center py-0">Pinned</MenuLabel>
            <TicketRows
              tickets={pinnedTickets}
              activeTicketId={activeTicketId}
              pinnedAtById={pinnedAtById}
            />
            <div className="my-1 border-border border-b" />
          </>
        )}

        <TicketRows
          tickets={unpinnedTickets}
          activeTicketId={activeTicketId}
          pinnedAtById={pinnedAtById}
        />

        {hasNextPage && (
          <div ref={loadMoreRef} className="flex justify-center py-2">
            {isFetchingNextPage && <Spinner className="size-4 text-gray-9" />}
          </div>
        )}
      </div>
    </div>
  );
}

function TicketRows({
  tickets,
  activeTicketId,
  pinnedAtById,
}: {
  tickets: SupportTicket[];
  activeTicketId?: string;
  pinnedAtById: Record<string, number>;
}) {
  const now = Date.now();

  return (
    <div className="flex flex-col gap-px">
      {tickets.map((ticket) => (
        <TicketRow
          key={ticket.id}
          ticket={ticket}
          now={now}
          isActive={ticket.id === activeTicketId}
          isPinned={pinnedAtById[ticket.id] !== undefined}
          onSelect={() => navigateToSupportTicket(ticket.id)}
        />
      ))}
    </div>
  );
}
