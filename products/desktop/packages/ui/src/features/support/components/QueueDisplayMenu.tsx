import { CaretDownIcon, SlidersIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { useSupportQueueStore } from "../supportQueueStore";
import {
  QUEUE_COLUMNS,
  type QueueSortField,
  TOGGLEABLE_QUEUE_COLUMNS,
} from "../ticketPresentation";

const ATTENTION = "attention";

const SORTABLE_COLUMNS = QUEUE_COLUMNS.filter((column) => column.sortField);

/**
 * Which columns the queue shows, and which order it uses. Order lives here
 * alongside the columns because both shape the same list, and because the
 * attention ranking needs a named option a user can deliberately leave and
 * come back to — a header click alone hides that it was ever the default.
 */
export function QueueDisplayMenu() {
  const visibleColumnIds = useSupportQueueStore(
    (state) => state.visibleColumnIds,
  );
  const sort = useSupportQueueStore((state) => state.sort);
  const setColumnVisible = useSupportQueueStore(
    (state) => state.setColumnVisible,
  );
  const toggleSort = useSupportQueueStore((state) => state.toggleSort);
  const clearSort = useSupportQueueStore((state) => state.clearSort);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button type="button" size="sm" variant="outline">
            <SlidersIcon size={13} />
            Display
            <CaretDownIcon size={11} className="opacity-60" />
          </Button>
        }
      />
      <DropdownMenuContent align="start" side="bottom" sideOffset={6}>
        <DropdownMenuGroup>
          <DropdownMenuLabel>Order</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={sort?.field ?? ATTENTION}
            onValueChange={(value: string) => {
              if (value === ATTENTION) clearSort();
              else if (value !== sort?.field)
                toggleSort(value as QueueSortField);
            }}
          >
            <DropdownMenuRadioItem value={ATTENTION}>
              Attention
            </DropdownMenuRadioItem>
            {SORTABLE_COLUMNS.map((column) => (
              <DropdownMenuRadioItem
                key={column.id}
                value={column.sortField as string}
              >
                {column.label}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel>Columns</DropdownMenuLabel>
          {TOGGLEABLE_QUEUE_COLUMNS.map((column) => (
            <DropdownMenuCheckboxItem
              key={column.id}
              checked={visibleColumnIds.includes(column.id)}
              onCheckedChange={(checked: boolean) =>
                setColumnVisible(column.id, checked)
              }
            >
              {column.label}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
