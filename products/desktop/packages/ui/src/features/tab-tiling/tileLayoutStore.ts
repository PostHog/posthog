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
        set((state) =>
          withGroups(
            state,
            state.groups.filter((g) => g.id !== groupId),
          ),
        ),
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
