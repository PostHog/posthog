import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  groupForTab,
  pruneActiveByGroup,
  pruneGroups,
  separateGroup,
  setSplitSizes,
  type TileEdge,
  type TileGroup,
  tileTab,
  untileTab,
} from "./tileLayout";

const STORAGE_KEY = "browser-tabs-tiling-storage";

/**
 * Which browser tabs share the content pane, and how it is divided between
 * them. View state persisted to localStorage, like pins: tab ids are durable
 * in SQLite, so a split survives relaunch, and the desktop app is single-window
 * so no cross-window sync is needed. Groups are pruned against the live
 * snapshot so a closed tab never leaves an empty tile behind.
 *
 * `activeByGroup` remembers the tile that was active last in each group, so
 * the strip's split pill can name it and reopen the split on it.
 */
interface TileLayoutStore {
  groups: TileGroup[];
  activeByGroup: Record<string, string>;
  tileTab: (tabId: string, targetTabId: string, edge: TileEdge) => void;
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
  return {
    groups,
    activeByGroup: pruneActiveByGroup(groups, state.activeByGroup),
  };
}

export const useTileLayoutStore = create<TileLayoutStore>()(
  persist(
    (set) => ({
      groups: [],
      activeByGroup: {},
      tileTab: (tabId, targetTabId, edge) =>
        set((state) =>
          withGroups(
            state,
            tileTab(state.groups, tabId, targetTabId, edge, () =>
              crypto.randomUUID(),
            ),
          ),
        ),
      untileTab: (tabId) =>
        set((state) => withGroups(state, untileTab(state.groups, tabId))),
      separate: (groupId) =>
        set((state) => withGroups(state, separateGroup(state.groups, groupId))),
      noteActive: (tabId) =>
        set((state) => {
          const group = groupForTab(state.groups, tabId);
          if (!group || state.activeByGroup[group.id] === tabId) return state;
          return {
            activeByGroup: { ...state.activeByGroup, [group.id]: tabId },
          };
        }),
      setSplitSizes: (splitId, sizes) =>
        set((state) =>
          withGroups(state, setSplitSizes(state.groups, splitId, sizes)),
        ),
      prune: (liveTabIds) =>
        set((state) =>
          withGroups(state, pruneGroups(state.groups, liveTabIds)),
        ),
    }),
    { name: STORAGE_KEY },
  ),
);
