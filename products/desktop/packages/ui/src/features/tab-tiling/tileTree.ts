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
  sizes?: number[];
}

export type TileNode = TileLeaf | TileSplit;

export interface TileGroup {
  id: string;
  root: TileNode;
}

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

export function nodeId(node: TileNode): string {
  return node.type === "tab" ? node.tabId : node.id;
}

function directionForEdge(edge: TileEdge): TileDirection {
  return edge === "left" || edge === "right" ? "horizontal" : "vertical";
}

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
  if (children.length === node.children.length) return { ...node, children };
  return { type: "split", id: node.id, direction: node.direction, children };
}

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

export function untileTab(groups: TileGroup[], tabId: string): TileGroup[] {
  const group = groupForTab(groups, tabId);
  if (!group) return groups;
  const root = removeLeaf(group.root, tabId);
  return groups.flatMap((g) => {
    if (g.id !== group.id) return [g];
    return root && root.type === "split" ? [{ id: g.id, root }] : [];
  });
}

export function tileTab(
  groups: TileGroup[],
  tabId: string,
  targetTabId: string,
  edge: TileEdge,
  makeId: () => string,
): TileGroup[] {
  if (tabId === targetTabId) return groups;
  const without = untileTab(groups, tabId);
  const existing = groupForTab(without, targetTabId);
  const targetRoot: TileNode = existing?.root ?? {
    type: "tab",
    tabId: targetTabId,
  };
  if (tabIdsIn(targetRoot).length >= MAX_TILES_PER_GROUP) return groups;
  const leaf: TileLeaf = { type: "tab", tabId };
  const root = insertBeside(targetRoot, targetTabId, leaf, edge, makeId);
  const next: TileGroup = { id: existing?.id ?? nodeId(root), root };
  return existing
    ? without.map((g) => (g.id === next.id ? next : g))
    : [...without, next];
}

export function lastActiveIn(
  group: TileGroup,
  activeByGroup: Readonly<Record<string, string>>,
): string {
  const ids = tabIdsIn(group.root);
  const remembered = activeByGroup[group.id];
  return remembered && ids.includes(remembered) ? remembered : ids[0];
}

export function focusedTabIn(
  groups: readonly TileGroup[],
  activeByGroup: Readonly<Record<string, string>>,
  tabId: string,
): string {
  const group = groupForTab(groups, tabId);
  return group ? lastActiveIn(group, activeByGroup) : tabId;
}

export function pruneActiveByGroup(
  groups: readonly TileGroup[],
  activeByGroup: Readonly<Record<string, string>>,
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const group of groups) {
    const tabId = activeByGroup[group.id];
    if (tabId && tabIdsIn(group.root).includes(tabId)) next[group.id] = tabId;
  }
  const same =
    Object.keys(next).length === Object.keys(activeByGroup).length &&
    Object.entries(next).every(([id, tabId]) => activeByGroup[id] === tabId);
  return same ? activeByGroup : next;
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
