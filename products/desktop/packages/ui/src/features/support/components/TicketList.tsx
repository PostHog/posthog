import {
  CaretDownIcon,
  MagnifyingGlassIcon,
  SpinnerGapIcon,
} from "@phosphor-icons/react";
import type { Schemas } from "@posthog/api-client";
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
  Text,
} from "@posthog/quill";
import { TicketRow } from "@posthog/ui/features/support/components/TicketRow";
import { useSupportTickets } from "@posthog/ui/features/support/hooks/useSupportTickets";
import { useSupportTicketViews } from "@posthog/ui/features/support/hooks/useSupportTicketViews";
import {
  QUEUE_STATUSES,
  type SupportAssigneeScope,
  useSupportQueueStore,
} from "@posthog/ui/features/support/supportQueueStore";
import { TICKET_STATUS_LABELS } from "@posthog/ui/features/support/ticketPresentation";
import { useDebounce } from "@posthog/ui/primitives/hooks/useDebounce";
import { navigateToSupportTicket } from "@posthog/ui/router/navigationBridge";
import { useMemo } from "react";

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

  const { data, isPending, isError } = useSupportTickets(listOptions);
  const tickets = data?.results ?? [];

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
            <SpinnerGapIcon size={16} className="animate-spin text-gray-9" />
          </div>
        )}

        {isError && !isPending && (
          <Text className="block p-3 text-[13px] text-muted-foreground">
            Could not load tickets. They will reappear when the connection
            recovers.
          </Text>
        )}

        {!isPending && !isError && tickets.length === 0 && (
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

        <TicketRows tickets={tickets} activeTicketId={activeTicketId} />
      </div>
    </div>
  );
}

function TicketRows({
  tickets,
  activeTicketId,
}: {
  tickets: SupportTicket[];
  activeTicketId?: string;
}) {
  const now = Date.now();
  const groups = useMemo(() => groupByStatus(tickets), [tickets]);

  return (
    <div className="flex flex-col gap-3">
      {groups.map(({ status, rows }) => (
        <div key={status} className="flex flex-col gap-px">
          <div className="flex items-center gap-1.5 px-2 py-1">
            <Text className="font-semibold text-[10px] text-muted-foreground uppercase tracking-wider">
              {TICKET_STATUS_LABELS[status]}
            </Text>
            <Text className="text-[10px] text-gray-11 tabular-nums">
              {rows.length}
            </Text>
          </div>
          {rows.map((ticket) => (
            <TicketRow
              key={ticket.id}
              ticket={ticket}
              now={now}
              isActive={ticket.id === activeTicketId}
              onSelect={() => navigateToSupportTicket(ticket.id)}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** The queue's statuses first, in queue order, then anything else the filters let through. */
function groupByStatus(
  tickets: SupportTicket[],
): { status: Schemas.TicketStatusEnum; rows: SupportTicket[] }[] {
  const byStatus = new Map<Schemas.TicketStatusEnum, SupportTicket[]>();
  for (const ticket of tickets) {
    const status = ticket.status ?? "new";
    const rows = byStatus.get(status);
    if (rows) {
      rows.push(ticket);
    } else {
      byStatus.set(status, [ticket]);
    }
  }

  const ordered = [
    ...QUEUE_STATUSES,
    ...[...byStatus.keys()].filter((s) => !QUEUE_STATUSES.includes(s)),
  ];
  return ordered
    .map((status) => ({ status, rows: byStatus.get(status) ?? [] }))
    .filter((group) => group.rows.length > 0);
}
