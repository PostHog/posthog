import type { SidebarNavItem } from "@posthog/shared/analytics-events";

export const SIDEBAR_MIN_WIDTH = 240;

export const CUSTOMIZABLE_NAV_ITEMS = [
  { id: "inbox", label: "Inbox", analyticsId: "inbox", defaultVisible: true },
  {
    id: "loops",
    label: "Loops",
    analyticsId: "loops",
    defaultVisible: true,
  },
  {
    id: "command-center",
    label: "Command Center",
    analyticsId: "command_center",
    defaultVisible: true,
  },
  {
    id: "contexts",
    label: "Channels",
    analyticsId: "contexts",
    defaultVisible: true,
  },
  {
    id: "activity",
    label: "Activity",
    analyticsId: "activity",
    defaultVisible: true,
  },
  {
    id: "configure",
    label: "Configure",
    analyticsId: "configure",
    defaultVisible: true,
  },
] as const satisfies readonly {
  id: string;
  label: string;
  analyticsId: SidebarNavItem;
  defaultVisible: boolean;
}[];

export type CustomizableNavItemId =
  (typeof CUSTOMIZABLE_NAV_ITEMS)[number]["id"];

export const CUSTOMIZABLE_NAV_ITEM_IDS = CUSTOMIZABLE_NAV_ITEMS.map(
  (item) => item.id,
);

export type NavItemOverrides = Partial<Record<CustomizableNavItemId, boolean>>;

const DEFAULT_VISIBILITY: Record<CustomizableNavItemId, boolean> =
  Object.fromEntries(
    CUSTOMIZABLE_NAV_ITEMS.map((item) => [item.id, item.defaultVisible]),
  ) as Record<CustomizableNavItemId, boolean>;

export function isNavItemVisible(
  overrides: NavItemOverrides,
  id: CustomizableNavItemId,
): boolean {
  return overrides[id] ?? DEFAULT_VISIBILITY[id];
}

export type CustomizableNavItem = (typeof CUSTOMIZABLE_NAV_ITEMS)[number];

/** Applies a stored drag order. Ids missing from it (newly shipped items)
 * slot in after their nearest default predecessor instead of at the end, so
 * users with a saved order still get new items near their intended spot. */
export function orderedNavItems(
  order: readonly CustomizableNavItemId[],
): readonly CustomizableNavItem[] {
  if (order.length === 0) return CUSTOMIZABLE_NAV_ITEMS;
  const byId = new Map(CUSTOMIZABLE_NAV_ITEMS.map((item) => [item.id, item]));
  const result = [...order];
  for (const [defaultIndex, item] of CUSTOMIZABLE_NAV_ITEMS.entries()) {
    if (result.includes(item.id)) continue;
    let insertAt = 0;
    for (let i = defaultIndex - 1; i >= 0; i--) {
      const neighbor = result.indexOf(CUSTOMIZABLE_NAV_ITEMS[i].id);
      if (neighbor !== -1) {
        insertAt = neighbor + 1;
        break;
      }
    }
    result.splice(insertAt, 0, item.id);
  }
  return result.flatMap((id) => {
    const item = byId.get(id);
    return item ? [item] : [];
  });
}

export function moveNavItem(
  order: readonly CustomizableNavItemId[],
  sourceId: string,
  targetId: string,
): readonly CustomizableNavItemId[] {
  const full = orderedNavItems(order).map((item) => item.id);
  const ids: readonly string[] = full;
  const from = ids.indexOf(sourceId);
  const to = ids.indexOf(targetId);
  if (from === -1 || to === -1 || from === to) return order;
  const [moved] = full.splice(from, 1);
  full.splice(to, 0, moved);
  return full;
}

export function sanitizeNavItemOrder(value: unknown): CustomizableNavItemId[] {
  if (!Array.isArray(value)) return [];
  const order = new Set<CustomizableNavItemId>();
  for (const entry of value) {
    const id = CUSTOMIZABLE_NAV_ITEM_IDS.find((known) => known === entry);
    if (id) order.add(id);
  }
  return [...order];
}

/** Keeps only known item ids with boolean values, so corrupt or stale
 * persisted state degrades to per-item defaults instead of crashing. */
export function sanitizeNavItemOverrides(value: unknown): NavItemOverrides {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  const overrides: NavItemOverrides = {};
  for (const id of CUSTOMIZABLE_NAV_ITEM_IDS) {
    const entry = (value as Record<string, unknown>)[id];
    if (typeof entry === "boolean") overrides[id] = entry;
  }
  return overrides;
}
