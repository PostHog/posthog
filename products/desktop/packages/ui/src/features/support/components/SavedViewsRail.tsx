import {
  FunnelSimpleIcon,
  MagnifyingGlassIcon,
  RowsIcon,
  StarIcon,
} from "@phosphor-icons/react";
import type { TicketView } from "@posthog/api-client/posthog-client";
import { Input } from "@posthog/quill";
import { useState } from "react";
import { useSetTicketViewFavorited } from "../hooks/useSetTicketViewFavorited";
import { groupSavedViews } from "../ticketPresentation";
import { SectionLabel } from "./SectionLabel";

/**
 * Row chrome shared by the built-in row and the saved-view rows so the two
 * can't drift. `bg-fill-selected` is the app's own selected-nav treatment
 * (see `SidebarItem`) — a soft tint that reads as a selected row in both
 * themes, where a saturated fill across a full-width rail row reads as a
 * banner. hogdesk's `accent` tokens don't exist in this palette.
 */
function rowClass(active: boolean): string {
  return `relative flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-left text-[13px] ${
    active
      ? "bg-fill-selected font-medium text-foreground"
      : "text-foreground hover:bg-fill-hover"
  }`;
}

/** Absolutely positioned, so the bar costs no layout width and stays inside
 *  the row's rounded corners. */
function ActiveBar() {
  return (
    <span
      aria-hidden
      className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-primary"
    />
  );
}

/**
 * The saved-views rail: a built-in "All tickets" row, favorited views, then
 * the rest. Owned by Support rather than contributed to the app's
 * `ChannelsSidebar` — these are a queue control, not an app destination.
 */
export function SavedViewsRail({
  views,
  isPending,
  isError,
  activeShortId,
  onSelect,
}: {
  views: TicketView[] | undefined;
  isPending: boolean;
  isError: boolean;
  activeShortId: string | null;
  onSelect: (shortId: string | null) => void;
}) {
  const [search, setSearch] = useState("");
  const setFavorited = useSetTicketViewFavorited();
  const { favorited, other, showSearch, noMatches } = groupSavedViews(
    views ?? [],
    search,
  );

  const row = (view: TicketView) => (
    <SavedViewRow
      key={view.short_id}
      view={view}
      active={activeShortId === view.short_id}
      onSelect={() => onSelect(view.short_id)}
      onToggleFavorite={() =>
        setFavorited.mutate({
          shortId: view.short_id,
          favorited: !view.is_favorited,
        })
      }
    />
  );

  return (
    <aside className="flex w-60 shrink-0 flex-col gap-2 overflow-y-auto border-border border-r p-3">
      <ul>
        <li className="group relative flex items-center">
          <button
            type="button"
            onClick={() => onSelect(null)}
            aria-current={activeShortId === null ? "true" : undefined}
            className={rowClass(activeShortId === null)}
          >
            {activeShortId === null && <ActiveBar />}
            <RowsIcon size={14} className="shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">All tickets</span>
          </button>
        </li>
      </ul>

      {favorited.length > 0 && (
        <>
          <SectionLabel>Favorited views</SectionLabel>
          <ul className="space-y-0.5">{favorited.map(row)}</ul>
          <div className="border-border border-t" />
        </>
      )}

      <SectionLabel>Saved views</SectionLabel>

      {showSearch && (
        <div className="relative">
          <MagnifyingGlassIcon
            size={13}
            className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2 text-muted-foreground"
          />
          <Input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search views"
            aria-label="Search saved views"
            className="h-7 pl-7 text-[12px]"
          />
        </div>
      )}

      <ul className="space-y-0.5">
        {other.map(row)}
        {isPending && <RailNote>Loading…</RailNote>}
        {isError && <RailNote>Couldn't load saved views.</RailNote>}
        {!isPending && !isError && (views?.length ?? 0) === 0 && (
          <RailNote>No saved views yet. Create them in PostHog.</RailNote>
        )}
        {noMatches && <RailNote>No views match “{search.trim()}”.</RailNote>}
      </ul>
    </aside>
  );
}

function SavedViewRow({
  view,
  active,
  onSelect,
  onToggleFavorite,
}: {
  view: TicketView;
  active: boolean;
  onSelect: () => void;
  onToggleFavorite: () => void;
}) {
  const favorited = Boolean(view.is_favorited);
  return (
    <li className="group relative flex items-center">
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        className={rowClass(active)}
        title={view.name}
      >
        {active && <ActiveBar />}
        <FunnelSimpleIcon
          size={14}
          className={`shrink-0 ${active ? "" : "text-muted-foreground"}`}
        />
        {/* Room for the trailing action so a long name can't run under it. */}
        <span className="min-w-0 flex-1 truncate pr-5">{view.name}</span>
      </button>
      {/* Hover-revealed, but `focus-visible` keeps it reachable by keyboard —
          `invisible` alone would strand it. */}
      <button
        type="button"
        onClick={onToggleFavorite}
        title={favorited ? "Unfavorite view" : "Favorite view"}
        aria-label={`${favorited ? "Unfavorite" : "Favorite"} ${view.name}`}
        aria-pressed={favorited}
        className={`absolute right-1 shrink-0 cursor-pointer rounded p-1 hover:bg-fill-hover focus-visible:visible ${
          favorited
            ? "visible text-warning-foreground"
            : "invisible text-muted-foreground hover:text-foreground group-hover:visible"
        }`}
      >
        <StarIcon size={12} weight={favorited ? "fill" : "regular"} />
      </button>
    </li>
  );
}

function RailNote({ children }: { children: React.ReactNode }) {
  return (
    <li className="px-2 py-1 text-[11px] text-muted-foreground">{children}</li>
  );
}
