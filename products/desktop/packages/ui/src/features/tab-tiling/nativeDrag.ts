import { CANVAS_DRAG_TYPE } from "@posthog/ui/features/canvas/canvasDrag";
import { TASK_DRAG_TYPE } from "@posthog/ui/features/sidebar/taskDrag";
import { useEffect } from "react";
import { create } from "zustand";

export type NativeDragKind = "task" | "canvas";

interface NativeDragStore {
  kind: NativeDragKind | null;
  setKind: (kind: NativeDragKind | null) => void;
}

export const useNativeDragStore = create<NativeDragStore>((set) => ({
  kind: null,
  setKind: (kind) => set((state) => (state.kind === kind ? state : { kind })),
}));

export function nativeDragKindOf(
  dataTransfer: Pick<DataTransfer, "types"> | null,
): NativeDragKind | null {
  const types = dataTransfer?.types;
  if (!types) return null;
  if (types.includes(TASK_DRAG_TYPE)) return "task";
  if (types.includes(CANVAS_DRAG_TYPE)) return "canvas";
  return null;
}

export function useNativeDragWatcher(): void {
  useEffect(() => {
    const setKind = useNativeDragStore.getState().setKind;
    const onEnter = (event: DragEvent) =>
      setKind(nativeDragKindOf(event.dataTransfer));
    const onLeaveWindow = (event: DragEvent) => {
      if (event.relatedTarget === null) setKind(null);
    };
    const clear = () => setKind(null);
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeaveWindow);
    window.addEventListener("drop", clear);
    window.addEventListener("dragend", clear);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeaveWindow);
      window.removeEventListener("drop", clear);
      window.removeEventListener("dragend", clear);
    };
  }, []);
}
