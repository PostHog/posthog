import type { SidebarNavItem } from "@posthog/shared/analytics-events";

export const SIDEBAR_MIN_WIDTH = 240;

/**
 * Wider floor for the channels layout only. The title bar's left strip is
 * pinned to the sidebar width and none of its contents shrink; that layout
 * adds a search button, taking the strip to 228px, so 240 would leave the two
 * groups touching. Off, the strip needs 208px and keeps the usual floor.
 */
export const CHANNELS_SIDEBAR_MIN_WIDTH = 272;

/** Sits outside the sidebar, so anything measuring from the window's left edge
 *  has to add it. */
export const NAV_RAIL_WIDTH = 44;

export const NAV_ITEMS = [
  { id: "inbox", label: "Self-driving", analyticsId: "inbox" },
  { id: "activity", label: "Activity", analyticsId: "activity" },
  { id: "loops", label: "Loops", analyticsId: "loops" },
  {
    id: "command-center",
    label: "Command Center",
    analyticsId: "command_center",
  },
  { id: "contexts", label: "Context", analyticsId: "contexts" },
  { id: "configure", label: "Settings", analyticsId: "configure" },
] as const satisfies readonly {
  id: string;
  label: string;
  analyticsId: SidebarNavItem;
}[];

export type NavItemId = (typeof NAV_ITEMS)[number]["id"];
