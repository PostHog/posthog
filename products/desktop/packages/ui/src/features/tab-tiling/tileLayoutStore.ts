import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  pruneGroups,
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
 */
interface TileLayoutStore {
  groups: TileGroup[];
  tileTab: (tabId: string, targetTabId: string, edge: TileEdge) => void;
  untileTab: (tabId: string) => void;
  setSplitSizes: (splitId: string, sizes: number[]) => void;
  prune: (liveTabIds: string[]) => void;
}

export const useTileLayoutStore = create<TileLayoutStore>()(
  persist(
    (set) => ({
      groups: [],
      tileTab: (tabId, targetTabId, edge) =>
        set((state) => ({
          groups: tileTab(state.groups, tabId, targetTabId, edge, () =>
            crypto.randomUUID(),
          ),
        })),
      untileTab: (tabId) =>
        set((state) => ({ groups: untileTab(state.groups, tabId) })),
      setSplitSizes: (splitId, sizes) =>
        set((state) => {
          const next = setSplitSizes(state.groups, splitId, sizes);
          return next === state.groups ? state : { groups: next };
        }),
      prune: (liveTabIds) =>
        set((state) => {
          const next = pruneGroups(state.groups, liveTabIds);
          return next === state.groups ? state : { groups: next };
        }),
    }),
    { name: STORAGE_KEY },
  ),
);
