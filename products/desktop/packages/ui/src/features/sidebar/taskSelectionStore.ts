import {
  computeRangeSelection,
  dedupeTaskIds,
  pruneToVisible,
} from "@posthog/core/sidebar/selection";
import { create } from "zustand";

interface TaskSelectionState {
  selectedTaskIds: string[];
  /** The last task ID that was clicked — used as the anchor for shift-click range selection. */
  lastClickedId: string | null;
}

interface TaskSelectionActions {
  /** Replace the entire selection (plain click). */
  setSelectedTaskIds: (taskIds: string[]) => void;
  /** Toggle a single task in/out of the selection (cmd-click). */
  toggleTaskSelection: (taskId: string) => void;
  /** Select a contiguous range from the last-clicked task to `toId` within the given ordered list.
   *  Existing selection outside the range is preserved (shift-click behavior).
   *  If there is no last-clicked anchor (e.g. the user just navigated via a plain click),
   *  `fallbackAnchorId` is used — typically the currently active/routed task. */
  selectRange: (
    toId: string,
    orderedIds: string[],
    fallbackAnchorId?: string | null,
  ) => void;
  isTaskSelected: (taskId: string) => boolean;
  clearSelection: () => void;
  pruneSelection: (visibleTaskIds: string[]) => void;
}

type TaskSelectionStore = TaskSelectionState & TaskSelectionActions;

export const useTaskSelectionStore = create<TaskSelectionStore>()(
  (set, get) => ({
    selectedTaskIds: [],
    lastClickedId: null,

    setSelectedTaskIds: (taskIds) =>
      set({
        selectedTaskIds: dedupeTaskIds(taskIds),
        lastClickedId: taskIds.length === 1 ? taskIds[0] : get().lastClickedId,
      }),

    toggleTaskSelection: (taskId) =>
      set((state) => {
        const isRemoving = state.selectedTaskIds.includes(taskId);
        return {
          selectedTaskIds: isRemoving
            ? state.selectedTaskIds.filter((id) => id !== taskId)
            : [...state.selectedTaskIds, taskId],
          lastClickedId: taskId,
        };
      }),

    selectRange: (toId, orderedIds, fallbackAnchorId) =>
      set((state) =>
        computeRangeSelection(
          state.lastClickedId ?? fallbackAnchorId ?? null,
          toId,
          orderedIds,
          state.selectedTaskIds,
        ),
      ),

    isTaskSelected: (taskId) => get().selectedTaskIds.includes(taskId),

    clearSelection: () => set({ selectedTaskIds: [], lastClickedId: null }),

    pruneSelection: (visibleTaskIds) =>
      set((state) => {
        const filtered = pruneToVisible(state.selectedTaskIds, visibleTaskIds);
        if (filtered.length === state.selectedTaskIds.length) {
          return state;
        }
        return { selectedTaskIds: filtered };
      }),
  }),
);
