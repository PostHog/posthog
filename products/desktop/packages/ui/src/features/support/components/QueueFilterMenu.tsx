import { CaretDownIcon, FunnelIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { Fragment } from "react";
import type { QueueFilters } from "../ticketPresentation";
import { queueFilterChips } from "../ticketPresentation";

const ANY = "any";

interface FilterGroup {
  key: keyof Omit<QueueFilters, "search">;
  label: string;
  options: Array<{ value: string; label: string }>;
}

// Every option here maps to a filter the tickets endpoint actually supports;
// anything it can't express belongs in the ranking, not in a dead control.
const FILTER_GROUPS: FilterGroup[] = [
  {
    key: "status",
    label: "Status",
    options: [
      { value: "new", label: "New" },
      { value: "open", label: "Open" },
      { value: "pending", label: "Pending" },
      { value: "on_hold", label: "On hold" },
      { value: "resolved", label: "Resolved" },
    ],
  },
  {
    key: "priority",
    label: "Priority",
    options: [
      { value: "high", label: "High" },
      { value: "medium", label: "Medium" },
      { value: "low", label: "Low" },
    ],
  },
  {
    key: "channel",
    label: "Channel",
    options: [
      { value: "email", label: "Email" },
      { value: "slack", label: "Slack" },
      { value: "teams", label: "Teams" },
      { value: "widget", label: "Widget" },
    ],
  },
  {
    key: "sla",
    label: "SLA",
    options: [
      { value: "breached", label: "Breached" },
      { value: "at-risk", label: "At risk" },
      { value: "on-track", label: "On track" },
    ],
  },
  {
    key: "assignee",
    label: "Assignee",
    options: [
      { value: "me", label: "Me" },
      { value: "unassigned", label: "Unassigned" },
    ],
  },
];

export function QueueFilterMenu({
  filters,
  onChange,
}: {
  filters: QueueFilters;
  onChange: (next: QueueFilters) => void;
}) {
  const activeCount = queueFilterChips(filters).length;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button type="button" size="sm" variant="outline">
            <FunnelIcon size={13} />
            Filters
            {activeCount > 0 && (
              <span className="rounded-full bg-muted px-1.5 font-medium text-[10px] text-muted-foreground">
                {activeCount}
              </span>
            )}
            <CaretDownIcon size={11} className="opacity-60" />
          </Button>
        }
      />
      <DropdownMenuContent align="start" side="bottom" sideOffset={6}>
        {FILTER_GROUPS.map((group, index) => (
          <Fragment key={group.key}>
            {index > 0 && <DropdownMenuSeparator />}
            <DropdownMenuGroup>
              <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={filters[group.key] ?? ANY}
                onValueChange={(value: string) =>
                  onChange({
                    ...filters,
                    [group.key]: value === ANY ? null : value,
                  })
                }
              >
                <DropdownMenuRadioItem value={ANY}>Any</DropdownMenuRadioItem>
                {group.options.map((option) => (
                  <DropdownMenuRadioItem
                    key={option.value}
                    value={option.value}
                  >
                    {option.label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
          </Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
