import { create } from "zustand";

interface ArchivingTasksState {
  /** Task IDs with an archive request currently in flight. */
  archivingTaskIds: Set<string>;
  hiddenArchivingTaskIds: Set<string>;
}

interface ArchivingTasksActions {
  isArchiving: (taskId: string) => boolean;
  shouldHideWhileArchiving: (taskId: string) => boolean;
  startArchiving: (
    taskId: string,
    presentation?: "progress" | "hidden",
  ) => void;
  stopArchiving: (taskId: string) => void;
}

type ArchivingTasksStore = ArchivingTasksState & ArchivingTasksActions;

/**
 * Tracks which tasks are mid-archive so single-task actions can render progress
 * while bulk actions remove rows immediately. Pending rows ignore interactions
 * until the archive resolves.
 */
export const useArchivingTasksStore = create<ArchivingTasksStore>(
  (set, get) => ({
    archivingTaskIds: new Set(),
    hiddenArchivingTaskIds: new Set(),

    isArchiving: (taskId) => get().archivingTaskIds.has(taskId),
    shouldHideWhileArchiving: (taskId) =>
      get().hiddenArchivingTaskIds.has(taskId),

    startArchiving: (taskId, presentation = "progress") =>
      set((state) => {
        if (state.archivingTaskIds.has(taskId)) return state;
        const archivingTaskIds = new Set(state.archivingTaskIds);
        archivingTaskIds.add(taskId);
        const hiddenArchivingTaskIds = new Set(state.hiddenArchivingTaskIds);
        if (presentation === "hidden") hiddenArchivingTaskIds.add(taskId);
        return { archivingTaskIds, hiddenArchivingTaskIds };
      }),

    stopArchiving: (taskId) =>
      set((state) => {
        if (!state.archivingTaskIds.has(taskId)) return state;
        const archivingTaskIds = new Set(state.archivingTaskIds);
        archivingTaskIds.delete(taskId);
        const hiddenArchivingTaskIds = new Set(state.hiddenArchivingTaskIds);
        hiddenArchivingTaskIds.delete(taskId);
        return { archivingTaskIds, hiddenArchivingTaskIds };
      }),
  }),
);
