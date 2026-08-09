import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  DEFAULT_VISIBLE_COLUMN_IDS,
  type QueueSort,
  type QueueSortField,
} from "./ticketPresentation";

const STORAGE_KEY = "support-queue-display";

/**
 * How the queue is displayed: which columns are on, and whether a column sort
 * is currently overriding the attention ranking.
 *
 * Only the columns persist. The sort override deliberately resets to the
 * ranking on every launch — a column order left on last week would silently
 * bury whatever needs attention today, with nothing on screen to say why.
 */
interface SupportQueueStore {
  visibleColumnIds: string[];
  sort: QueueSort | null;
  setColumnVisible: (id: string, visible: boolean) => void;
  /** Cycles ascending → descending → back to the attention ranking. */
  toggleSort: (field: QueueSortField) => void;
  clearSort: () => void;
}

export const useSupportQueueStore = create<SupportQueueStore>()(
  persist(
    (set) => ({
      visibleColumnIds: [...DEFAULT_VISIBLE_COLUMN_IDS],
      sort: null,
      setColumnVisible: (id, visible) =>
        set((state) => ({
          visibleColumnIds: visible
            ? state.visibleColumnIds.includes(id)
              ? state.visibleColumnIds
              : [...state.visibleColumnIds, id]
            : state.visibleColumnIds.filter((columnId) => columnId !== id),
        })),
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
      partialize: (state) => ({ visibleColumnIds: state.visibleColumnIds }),
    },
  ),
);
