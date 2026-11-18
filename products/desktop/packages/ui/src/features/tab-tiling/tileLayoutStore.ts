import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  groupForTab,
  pruneActiveByGroup,
  pruneGroups,
  setSplitSizes,
  type TileEdge,
  type TileGroup,
  tileTab,
  untileTab,
} from "./tileTree";

const STORAGE_KEY = "browser-tabs-tiling-storage";

interface TileLayoutStore {
  groups: TileGroup[];
  activeByGroup: Record<string, string>;
  names: Record<string, string>;
  nextSplitNumber: number;
  tileTab: (tabId: string, targetTabId: string, edge: TileEdge) => void;
  renameGroup: (groupId: string, name: string) => void;
  untileTab: (tabId: string) => void;
  separate: (groupId: string) => void;
  noteActive: (tabId: string) => void;
  setSplitSizes: (splitId: string, sizes: number[]) => void;
  prune: (liveTabIds: string[]) => void;
}

function withGroups(
  state: TileLayoutStore,
  groups: TileGroup[],
): Partial<TileLayoutStore> {
  if (groups === state.groups) return state;
  const named = nameNewGroups(
    groups,
    pruneNames(groups, state.names),
    state.nextSplitNumber,
  );
  return {
    groups,
    activeByGroup: pruneActiveByGroup(groups, state.activeByGroup),
    names: named.names,
    nextSplitNumber: named.next,
  };
}

function nameNewGroups(
  groups: TileGroup[],
  names: Record<string, string>,
  next: number,
): { names: Record<string, string>; next: number } {
  const unnamed = groups.filter((g) => !names[g.id]);
  if (unnamed.length === 0) return { names, next };
  const out = { ...names };
  let n = next;
  for (const g of unnamed) out[g.id] = `Split ${n++}`;
  return { names: out, next: n };
}

function pruneNames(
  groups: TileGroup[],
  names: Record<string, string>,
): Record<string, string> {
  const live = groups.filter((g) => names[g.id]);
  if (live.length === Object.keys(names).length) return names;
  return Object.fromEntries(live.map((g) => [g.id, names[g.id]]));
}

export const useTileLayoutStore = create<TileLayoutStore>()(
  persist(
    (set, get) => {
      const update = (
        next: (state: TileLayoutStore) => Partial<TileLayoutStore>,
      ) => {
        const state = get();
        const partial = next(state);
        if (partial !== state) set(partial);
      };
      const updateGroups = (next: (state: TileLayoutStore) => TileGroup[]) =>
        update((state) => withGroups(state, next(state)));
      return {
        groups: [],
        activeByGroup: {},
        names: {},
        nextSplitNumber: 1,
        renameGroup: (groupId, name) =>
          update((state) => {
            const trimmed = name.trim();
            if (trimmed) {
              return { names: { ...state.names, [groupId]: trimmed } };
            }
            return {
              names: {
                ...state.names,
                [groupId]: `Split ${state.nextSplitNumber}`,
              },
              nextSplitNumber: state.nextSplitNumber + 1,
            };
          }),
        tileTab: (tabId, targetTabId, edge) =>
          updateGroups((state) =>
            tileTab(state.groups, tabId, targetTabId, edge, () =>
              crypto.randomUUID(),
            ),
          ),
        untileTab: (tabId) =>
          updateGroups((state) => untileTab(state.groups, tabId)),
        separate: (groupId) =>
          updateGroups((state) => state.groups.filter((g) => g.id !== groupId)),
        noteActive: (tabId) =>
          update((state) => {
            const group = groupForTab(state.groups, tabId);
            if (!group || state.activeByGroup[group.id] === tabId) return state;
            return {
              activeByGroup: { ...state.activeByGroup, [group.id]: tabId },
            };
          }),
        setSplitSizes: (splitId, sizes) =>
          updateGroups((state) => setSplitSizes(state.groups, splitId, sizes)),
        prune: (liveTabIds) =>
          updateGroups((state) => pruneGroups(state.groups, liveTabIds)),
      };
    },
    { name: STORAGE_KEY },
  ),
);
