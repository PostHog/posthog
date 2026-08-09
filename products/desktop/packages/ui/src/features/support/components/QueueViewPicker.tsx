import { BookmarkSimpleIcon, CaretDownIcon } from "@phosphor-icons/react";
import type { TicketView } from "@posthog/api-client/posthog-client";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@posthog/quill";

// Sentinel for "no view", because a radio group's value can't be null.
const ALL_TICKETS = "all";

export const ALL_TICKETS_LABEL = "All tickets";

/**
 * Applies a saved view the team defined elsewhere. Read-only: views are
 * created and edited in PostHog, and picking one here only sends its
 * `short_id` for the server to expand.
 */
export function QueueViewPicker({
  views,
  isPending,
  isError,
  activeShortId,
  onChange,
}: {
  views: TicketView[] | undefined;
  isPending: boolean;
  isError: boolean;
  activeShortId: string | null;
  onChange: (shortId: string | null) => void;
}) {
  const active = views?.find((view) => view.short_id === activeShortId);
  const hasViews = (views?.length ?? 0) > 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button type="button" size="sm" variant="outline">
            <BookmarkSimpleIcon size={13} />
            {/* A view whose name hasn't resolved still names itself, so the
                trigger never silently reads "All tickets" while scoped. */}
            {activeShortId
              ? (active?.name ?? activeShortId)
              : ALL_TICKETS_LABEL}
            <CaretDownIcon size={11} className="opacity-60" />
          </Button>
        }
      />
      <DropdownMenuContent align="start" side="bottom" sideOffset={6}>
        <DropdownMenuGroup>
          <DropdownMenuLabel>Saved views</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={activeShortId ?? ALL_TICKETS}
            onValueChange={(value: string) =>
              onChange(value === ALL_TICKETS ? null : value)
            }
          >
            <DropdownMenuRadioItem value={ALL_TICKETS}>
              {ALL_TICKETS_LABEL}
            </DropdownMenuRadioItem>
            {views?.map((view) => (
              <DropdownMenuRadioItem key={view.short_id} value={view.short_id}>
                {view.name}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        {/* Plain text, not disabled menu items: none of these are choices. */}
        {isPending && <PickerNote>Loading saved views…</PickerNote>}
        {isError && <PickerNote>Couldn't load saved views.</PickerNote>}
        {!isPending && !isError && !hasViews && (
          <PickerNote>No saved views yet. Create them in PostHog.</PickerNote>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function PickerNote({ children }: { children: string }) {
  return (
    <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
      {children}
    </div>
  );
}
