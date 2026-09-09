import type { SketchpadViewport } from "@posthog/shared";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export const DEFAULT_SKETCHPAD_VIEWPORT: SketchpadViewport = {
  x: 0,
  y: 0,
  zoom: 1,
};

interface SketchpadLocalState {
  viewport: SketchpadViewport;
  taskId?: string;
}

interface SketchpadViewportState {
  boards: Record<string, SketchpadLocalState>;
  setViewport: (sketchpadId: string, viewport: SketchpadViewport) => void;
  setTaskForSketchpad: (
    sketchpadId: string,
    taskId: string | undefined,
  ) => void;
}

export const useSketchpadViewportStore = create<SketchpadViewportState>()(
  persist(
    (set) => ({
      boards: {},
      setViewport: (sketchpadId, viewport) => {
        set((state) => ({
          boards: {
            ...state.boards,
            [sketchpadId]: { ...state.boards[sketchpadId], viewport },
          },
        }));
      },
      setTaskForSketchpad: (sketchpadId, taskId) => {
        set((state) => ({
          boards: {
            ...state.boards,
            [sketchpadId]: {
              viewport:
                state.boards[sketchpadId]?.viewport ??
                DEFAULT_SKETCHPAD_VIEWPORT,
              taskId,
            },
          },
        }));
      },
    }),
    {
      name: "posthog-code-sketchpad-viewports",
      storage: electronStorage,
      partialize: (state) => ({ boards: state.boards }),
    },
  ),
);

export function useSketchpadViewport(sketchpadId: string): SketchpadViewport {
  return useSketchpadViewportStore(
    (state) =>
      state.boards[sketchpadId]?.viewport ?? DEFAULT_SKETCHPAD_VIEWPORT,
  );
}

export function useSketchpadTaskId(sketchpadId: string): string | undefined {
  return useSketchpadViewportStore(
    (state) => state.boards[sketchpadId]?.taskId,
  );
}

export async function sketchpadIdForTask(
  taskId: string,
): Promise<string | undefined> {
  if (!useSketchpadViewportStore.persist.hasHydrated()) {
    await useSketchpadViewportStore.persist.rehydrate();
  }
  return Object.entries(useSketchpadViewportStore.getState().boards).find(
    ([, board]) => board.taskId === taskId,
  )?.[0];
}

export function setTaskForSketchpad(
  sketchpadId: string,
  taskId: string | undefined,
): void {
  useSketchpadViewportStore.getState().setTaskForSketchpad(sketchpadId, taskId);
}
