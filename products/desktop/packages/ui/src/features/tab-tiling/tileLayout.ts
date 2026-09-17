/**
 * Pure model for tiled browser tabs: a group is a tree whose leaves are tab
 * ids and whose inner nodes split their children along one axis. Two tabs side
 * by side is `split(horizontal, [a, b])`; a 2x2 grid is a horizontal split of
 * two vertical splits. Every transform returns a new array and leaves the input
 * untouched, so the store can compare by reference.
 */
export type TileEdge = "left" | "right" | "top" | "bottom";
export type TileDirection = "horizontal" | "vertical";

export interface TileLeaf {
  type: "tab";
  tabId: string;
}

export interface TileSplit {
  type: "split";
  id: string;
  direction: TileDirection;
  children: TileNode[];
  /** Percent per child, in child order. Unset = equal shares. */
  sizes?: number[];
}

export type TileNode = TileLeaf | TileSplit;

export interface TileGroup {
  id: string;
  root: TileNode;
}

/** A group past this many tiles stops accepting drops; each tile gets too small. */
export const MAX_TILES_PER_GROUP = 4;

export function tabIdsIn(node: TileNode): string[] {
  return node.type === "tab"
    ? [node.tabId]
    : node.children.flatMap((child) => tabIdsIn(child));
}

export function groupForTab(
  groups: readonly TileGroup[],
  tabId: string,
): TileGroup | null {
  return groups.find((g) => tabIdsIn(g.root).includes(tabId)) ?? null;
}

function nodeId(node: TileNode): string {
  return node.type === "tab" ? node.tabId : node.id;
}

function directionForEdge(edge: TileEdge): TileDirection {
  return edge === "left" || edge === "right" ? "horizontal" : "vertical";
}

/**
 * Remove a leaf from a node. A split left with one child collapses into that
 * child; sizes are dropped because the remaining shares no longer add up.
 */
function removeLeaf(node: TileNode, tabId: string): TileNode | null {
  if (node.type === "tab") return node.tabId === tabId ? null : node;
  const children = node.children
    .map((child) => removeLeaf(child, tabId))
    .filter((child): child is TileNode => child !== null);
  const unchanged =
    children.length === node.children.length &&
    children.every((child, i) => child === node.children[i]);
  if (unchanged) return node;
  if (children.length === 0) return null;
  if (children.length === 1) return children[0];
  return { type: "split", id: node.id, direction: node.direction, children };
}

/**
 * Place `leaf` beside the target leaf. When the target's parent already splits
 * along the same axis the new leaf becomes a sibling, so three tabs in a row
 * stay one flat split instead of nesting.
 */
function insertBeside(
  node: TileNode,
  targetTabId: string,
  leaf: TileLeaf,
  edge: TileEdge,
  makeId: () => string,
): TileNode {
  const direction = directionForEdge(edge);
  const before = edge === "left" || edge === "top";
  if (node.type === "tab") {
    if (node.tabId !== targetTabId) return node;
    return {
      type: "split",
      id: makeId(),
      direction,
      children: before ? [leaf, node] : [node, leaf],
    };
  }
  const index = node.children.findIndex(
    (child) => child.type === "tab" && child.tabId === targetTabId,
  );
  if (index !== -1 && node.direction === direction) {
    const children = [...node.children];
    children.splice(before ? index : index + 1, 0, leaf);
    return { type: "split", id: node.id, direction, children };
  }
  return {
    ...node,
    children: node.children.map((child) =>
      insertBeside(child, targetTabId, leaf, edge, makeId),
    ),
  };
}

/** Drop a group once it holds fewer than two tiles; a lone tile is just a tab. */
export function untileTab(
  groups: readonly TileGroup[],
  tabId: string,
): TileGroup[] {
  const group = groupForTab(groups, tabId);
  if (!group) return [...groups];
  const root = removeLeaf(group.root, tabId);
  return groups.flatMap((g) => {
    if (g.id !== group.id) return [g];
    return root && root.type === "split" ? [{ id: g.id, root }] : [];
  });
}

/**
 * Tile `tabId` on the given edge of the tile that shows `targetTabId`. The
 * target joins a new group when it is not in one yet. Returns the input array
 * unchanged when the drop is a no-op or the target group is full.
 */
export function tileTab(
  groups: readonly TileGroup[],
  tabId: string,
  targetTabId: string,
  edge: TileEdge,
  makeId: () => string,
): TileGroup[] {
  if (tabId === targetTabId) return [...groups];
  const without = untileTab(groups, tabId);
  const existing = groupForTab(without, targetTabId);
  const targetRoot: TileNode = existing?.root ?? {
    type: "tab",
    tabId: targetTabId,
  };
  if (tabIdsIn(targetRoot).length >= MAX_TILES_PER_GROUP) return [...groups];
  const leaf: TileLeaf = { type: "tab", tabId };
  const root = insertBeside(targetRoot, targetTabId, leaf, edge, makeId);
  // A new group takes its first split's id, so one drop mints one id.
  const next: TileGroup = { id: existing?.id ?? nodeId(root), root };
  return existing
    ? without.map((g) => (g.id === next.id ? next : g))
    : [...without, next];
}

function sameSizes(a: number[] | undefined, b: number[]): boolean {
  return !!a && a.length === b.length && a.every((v, i) => v === b[i]);
}

function withSizes(node: TileNode, splitId: string, sizes: number[]): TileNode {
  if (node.type === "tab") return node;
  if (node.id === splitId) {
    return sameSizes(node.sizes, sizes) ? node : { ...node, sizes };
  }
  const children = node.children.map((child) =>
    withSizes(child, splitId, sizes),
  );
  return children.every((child, i) => child === node.children[i])
    ? node
    : { ...node, children };
}

/**
 * Record a split's shares after a resize. Returns the same array when nothing
 * changed, because the panel group reports its layout on mount too.
 */
export function setSplitSizes(
  groups: TileGroup[],
  splitId: string,
  sizes: number[],
): TileGroup[] {
  const next = groups.map((g) => {
    const root = withSizes(g.root, splitId, sizes);
    return root === g.root ? g : { id: g.id, root };
  });
  return next.every((g, i) => g === groups[i]) ? groups : next;
}

/**
 * Drop tiles whose tab was closed, and any group that collapses with them.
 * Returns the same array when nothing changed so a store can skip the update.
 */
export function pruneGroups(
  groups: TileGroup[],
  liveTabIds: readonly string[],
): TileGroup[] {
  const live = new Set(liveTabIds);
  let next = groups;
  for (const group of groups) {
    for (const tabId of tabIdsIn(group.root)) {
      if (!live.has(tabId)) next = untileTab(next, tabId);
    }
  }
  return next;
}
