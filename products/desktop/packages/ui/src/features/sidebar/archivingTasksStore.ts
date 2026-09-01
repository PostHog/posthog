import { create } from "zustand";

interface ArchivingTasksState {
  /** Task IDs with an archive request currently in flight. */
  archivingTaskIds: Set<string>;
}

interface ArchivingTasksActions {
  isArchiving: (taskId: string) => boolean;
  startArchiving: (taskId: string) => void;
  stopArchiving: (taskId: string) => void;
}

type ArchivingTasksStore = ArchivingTasksState & ArchivingTasksActions;

/**
 * Tracks which tasks are mid-archive so the sidebar can show a per-row spinner
 * and treat clicks, pin toggles, and right-clicks on those rows as no-ops until
 * the archive resolves.
 */
export const useArchivingTasksStore = create<ArchivingTasksStore>(
  (set, get) => ({
    archivingTaskIds: new Set(),

    isArchiving: (taskId) => get().archivingTaskIds.has(taskId),

    startArchiving: (taskId) =>
      set((state) => {
        if (state.archivingTaskIds.has(taskId)) return state;
        const next = new Set(state.archivingTaskIds);
        next.add(taskId);
        return { archivingTaskIds: next };
      }),

    stopArchiving: (taskId) =>
      set((state) => {
        if (!state.archivingTaskIds.has(taskId)) return state;
        const next = new Set(state.archivingTaskIds);
        next.delete(taskId);
        return { archivingTaskIds: next };
      }),
  }),
);
