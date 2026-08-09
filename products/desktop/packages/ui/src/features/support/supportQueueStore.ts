import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  DEFAULT_VISIBLE_COLUMN_IDS,
  type QueueSort,
  type QueueSortField,
} from "./ticketPresentation";

const STORAGE_KEY = "support-queue-display";

/**
 * How the queue is displayed: which columns are on, whether the saved-views
 * rail is open, and whether a column sort is overriding the attention ranking.
 *
 * **Persist display, never scope.** Columns and the rail's collapsed state
 * persist because neither changes which tickets are fetched. The sort override
 * doesn't, and neither does the applied view (which lives in the queue's own
 * filter state): either one left on from last week would silently reshape or
 * narrow today's queue with the reason off-screen.
 */
interface SupportQueueStore {
  visibleColumnIds: string[];
  railCollapsed: boolean;
  sort: QueueSort | null;
  setColumnVisible: (id: string, visible: boolean) => void;
  toggleRail: () => void;
  /** Cycles ascending → descending → back to the attention ranking. */
  toggleSort: (field: QueueSortField) => void;
  clearSort: () => void;
}

export const useSupportQueueStore = create<SupportQueueStore>()(
  persist(
    (set) => ({
      visibleColumnIds: [...DEFAULT_VISIBLE_COLUMN_IDS],
      railCollapsed: false,
      sort: null,
      setColumnVisible: (id, visible) =>
        set((state) => ({
          visibleColumnIds: visible
            ? state.visibleColumnIds.includes(id)
              ? state.visibleColumnIds
              : [...state.visibleColumnIds, id]
            : state.visibleColumnIds.filter((columnId) => columnId !== id),
        })),
      toggleRail: () =>
        set((state) => ({ railCollapsed: !state.railCollapsed })),
      toggleSort: (field) =>
        set((state) => {
          if (state.sort?.field !== field)
            return { sort: { field, desc: false } };
          return { sort: state.sort.desc ? null : { field, desc: true } };
        }),
      clearSort: () => set({ sort: null }),
    }),
    {
      name: STORAGE_KEY,
      partialize: (state) => ({
        visibleColumnIds: state.visibleColumnIds,
        railCollapsed: state.railCollapsed,
      }),
    },
  ),
);
