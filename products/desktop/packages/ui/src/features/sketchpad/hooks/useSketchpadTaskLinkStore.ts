import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { z } from "zod";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

interface SketchpadTaskLinkState {
  taskBySketchpad: Record<string, string | undefined>;
  setTaskForSketchpad: (
    sketchpadId: string,
    taskId: string | undefined,
  ) => void;
}

const legacyLinksSchema = z.object({
  state: z.object({
    boards: z.record(z.string(), z.object({ taskId: z.string().optional() })),
  }),
});

const storage = createJSONStorage<
  Pick<SketchpadTaskLinkState, "taskBySketchpad">
>(() => ({
  ...stateStorage,
  getItem: async (key) => {
    const current = await stateStorage.getItem(key);
    if (current !== null) return current;
    const legacy = await stateStorage.getItem(
      "posthog-code-sketchpad-viewports",
    );
    if (!legacy) return null;
    let value: unknown;
    try {
      value = JSON.parse(legacy);
    } catch {
      return null;
    }
    const parsed = legacyLinksSchema.safeParse(value);
    if (!parsed.success) return null;
    const taskBySketchpad = Object.fromEntries(
      Object.entries(parsed.data.state.boards).flatMap(([id, board]) =>
        board.taskId ? [[id, board.taskId]] : [],
      ),
    );
    const migrated = JSON.stringify({ state: { taskBySketchpad }, version: 0 });
    await stateStorage.setItem(key, migrated);
    return migrated;
  },
}));

export const useSketchpadTaskLinkStore = create<SketchpadTaskLinkState>()(
  persist(
    (set) => ({
      taskBySketchpad: {},
      setTaskForSketchpad: (sketchpadId, taskId) =>
        set((state) => ({
          taskBySketchpad: { ...state.taskBySketchpad, [sketchpadId]: taskId },
        })),
    }),
    {
      name: "posthog-code-sketchpad-task-links",
      storage,
      partialize: (state) => ({ taskBySketchpad: state.taskBySketchpad }),
    },
  ),
);

export function useSketchpadTaskId(sketchpadId: string): string | undefined {
  return useSketchpadTaskLinkStore(
    (state) => state.taskBySketchpad[sketchpadId],
  );
}

export async function sketchpadIdForTask(
  taskId: string,
): Promise<string | undefined> {
  if (!useSketchpadTaskLinkStore.persist.hasHydrated())
    await useSketchpadTaskLinkStore.persist.rehydrate();
  return Object.entries(
    useSketchpadTaskLinkStore.getState().taskBySketchpad,
  ).find(([, id]) => id === taskId)?.[0];
}

export function setTaskForSketchpad(
  sketchpadId: string,
  taskId: string | undefined,
): void {
  useSketchpadTaskLinkStore.getState().setTaskForSketchpad(sketchpadId, taskId);
}
