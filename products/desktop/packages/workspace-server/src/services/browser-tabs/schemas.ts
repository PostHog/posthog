import {
  type TabsSnapshot,
  tabsSnapshotSchema,
  tabViewStateSchema,
} from "@posthog/shared";
import { z } from "zod";

/**
 * Where `+` lands, and where an empty strip reseeds. The space index is the
 * app's "pick something" screen, so a new tab shows the spaces rather than an
 * empty placeholder.
 */
export const NEW_TAB_HREF = "/spaces";

/** tRPC output: the full durable tab/window snapshot. */
export const browserTabsSnapshotOutput = tabsSnapshotSchema;

/** The location a tab is on, plus the route-derived label/icon cache. */
const tabLocationFields = {
  href: z.string().nullable().default(null),
  viewState: tabViewStateSchema.nullable().default(null),
  dashboardId: z.string().nullable().default(null),
  taskId: z.string().nullable().default(null),
  channelId: z.string().nullable().default(null),
  channelSection: z.string().nullable().default(null),
  appView: z.string().nullable().default(null),
};

export const openTabInput = z.object({
  windowId: z.string(),
  ...tabLocationFields,
  // Renderer-minted id for the tab this call creates, so the optimistic local
  // apply and the persisted state agree on the id (local-first tab sync), and
  // a replayed call is idempotent.
  tabId: z.string().optional(),
});

export const setTabTargetInput = z.object({
  tabId: z.string(),
  ...tabLocationFields,
  activate: z.boolean().optional(),
});

export const closeTabInput = z.object({ tabId: z.string() });

export const closeTabsInput = z.object({
  tabIds: z.array(z.string()),
  // The bulk close's anchor (the right-clicked tab, which always survives);
  // focus falls to it when the active tab is among those closed.
  focusTabId: z.string().nullable().default(null),
});

export const setTabOrderInput = z.object({
  windowId: z.string(),
  tabIds: z.array(z.string()),
});

export const setActiveTabInput = z.object({
  windowId: z.string(),
  tabId: z.string().nullable(),
});

export enum BrowserTabsEvent {
  SnapshotChange = "snapshotChange",
}

export type BrowserTabsEvents = {
  [BrowserTabsEvent.SnapshotChange]: TabsSnapshot;
};
