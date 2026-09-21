import { Menu as BaseMenu } from "@base-ui/react/menu";
import { Check, Star } from "@phosphor-icons/react";
import {
  Autocomplete,
  AutocompleteCollection,
  AutocompleteGroup,
  AutocompleteInput,
  AutocompleteItem,
  AutocompleteList,
  AutocompleteStatus,
} from "@posthog/quill";
import { type ReactNode, useMemo, useState } from "react";

export type MenuFlyoutItem = {
  id: string;
  label: string;
  /** Marks the item with a tick — the one already in effect. */
  current: boolean;
  /** Sorts the item above the rest and marks it with a star. */
  starred?: boolean;
  icon?: ReactNode;
};

type MenuFlyoutSection = { items: MenuFlyoutItem[] };

/**
 * Submenu content pinned to its trigger row rather than allowed to drift.
 *
 * The default sub-content positioner re-aligns to avoid collisions, which for a
 * searchable flyout means the popup hops as the list filters and shrinks.
 * `collisionAvoidance: { align: "none" }` holds it against the trigger, and the
 * negative `alignOffset` lines the first item up with the row you opened it
 * from. Reaches for the Base UI parts directly because quill's
 * `*SubContent` doesn't expose collision avoidance.
 */
export function MenuSubFlyout({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <BaseMenu.Portal>
      <BaseMenu.Positioner
        data-quill
        data-quill-portal="popover"
        className="isolate outline-none"
        align="start"
        alignOffset={-3}
        side="inline-end"
        sideOffset={4}
        collisionAvoidance={{ align: "none" }}
      >
        <BaseMenu.Popup
          data-slot="dropdown-menu-sub-content"
          className={`quill-menu__content quill-menu__sub-content w-auto ${className ?? ""}`}
        >
          <div className="quill-menu__scroller scroll-mask-y-4 scroll-py-4">
            {children}
          </div>
        </BaseMenu.Popup>
      </BaseMenu.Positioner>
    </BaseMenu.Portal>
  );
}

export interface SearchableMenuFlyoutProps {
  items: MenuFlyoutItem[];
  placeholder: string;
  /** Shown when there are no items at all, as opposed to no matches. */
  emptyLabel: string;
  onSelect: (id: string) => void;
}

/**
 * A filterable list for inside a `MenuSubFlyout`: search input, tick on the
 * current item, keyboard-driven. Used by the project/organization switchers and
 * the task row's "File to…", so a long list of things to pick from behaves the
 * same wherever it appears.
 */
export function SearchableMenuFlyout({
  items,
  placeholder,
  emptyLabel,
  onSelect,
}: SearchableMenuFlyoutProps) {
  const [query, setQuery] = useState("");
  // Active item first as the anchor when switching, then the starred ones, the
  // same order the sidebar puts them in. Within each group, sorted the way the
  // web app orders them (locale-aware, which floats emoji-prefixed names above
  // plain ones).
  const sections = useMemo<MenuFlyoutSection[]>(() => {
    const rest = items
      .filter((item) => !item.current)
      .sort((a, b) => a.label.localeCompare(b.label));
    return [
      {
        items: [
          ...items.filter((item) => item.current),
          ...rest.filter((item) => item.starred),
          ...rest.filter((item) => !item.starred),
        ],
      },
    ];
  }, [items]);
  // A star column only where stars exist, and then on every row, so the labels
  // of unstarred items stay on the same line as the starred ones.
  const showStars = items.some((item) => item.starred);

  return (
    // Keep keystrokes away from the surrounding menu: its typeahead handler sits
    // on the submenu popup and would swallow typing meant for the search input.
    // Escape still bubbles so the menu can close.
    // biome-ignore lint/a11y/noStaticElementInteractions: keyboard fencing only
    <div
      onKeyDown={(event) => {
        if (event.key !== "Escape") event.stopPropagation();
      }}
    >
      <Autocomplete<MenuFlyoutItem>
        inline
        defaultOpen
        items={sections}
        value={query}
        autoHighlight="always"
        onValueChange={(val, eventDetails) => {
          if (eventDetails.reason !== "input-change") return;
          if (typeof val === "string") setQuery(val);
        }}
        filter={(item, q) => {
          if (!q) return true;
          return item.label.toLowerCase().includes(q.toLowerCase());
        }}
      >
        <AutocompleteInput placeholder={placeholder} autoFocus showClear />
        {/* Suppress the default "{count} results" line; only show empty states. */}
        <AutocompleteStatus>
          {(count: number) =>
            count === 0 ? (
              query ? (
                <span>
                  No matches for <strong>"{query}"</strong>
                </span>
              ) : (
                <span>{emptyLabel}</span>
              )
            ) : null
          }
        </AutocompleteStatus>
        {/* Long lists get a FIXED height so the popup doesn't resize (and jump)
            while filtering. Kept short enough that the whole flyout fits below
            either trigger row, so the popup itself never grows a second
            scrollbar. */}
        <AutocompleteList
          className={`${items.length > 5 ? "h-40" : "max-h-40"} p-0 pb-0`}
        >
          {(section: MenuFlyoutSection) => (
            <AutocompleteGroup items={section.items} className="p-0">
              <AutocompleteCollection>
                {(item: MenuFlyoutItem) => (
                  <AutocompleteItem
                    key={item.id}
                    value={item.id}
                    onClick={() => onSelect(item.id)}
                    className="flex items-center gap-2 ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0"
                  >
                    <span className="flex w-4 shrink-0 items-center justify-center">
                      {item.current && (
                        <Check size={14} className="text-accent-11" />
                      )}
                    </span>
                    {showStars && (
                      <span className="flex w-4 shrink-0 items-center justify-center">
                        {item.starred && (
                          <Star size={13} className="text-gray-9" />
                        )}
                      </span>
                    )}
                    {item.icon && (
                      <span className="flex shrink-0 items-center">
                        {item.icon}
                      </span>
                    )}
                    <span className="truncate text-[13px]">{item.label}</span>
                  </AutocompleteItem>
                )}
              </AutocompleteCollection>
            </AutocompleteGroup>
          )}
        </AutocompleteList>
      </Autocomplete>
    </div>
  );
}
