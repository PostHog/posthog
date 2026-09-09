import { create } from "zustand";

export type SketchpadPanelName = "palette" | "chat" | "history" | "inspector";

interface SketchpadViewState {
  selectedIds: string[];
  activePanel: SketchpadPanelName | null;
  highlightedIds: string[];
  focusedId: string | null;
  setSelection: (ids: string[]) => void;
  toggleSelection: (id: string) => void;
  clearSelection: () => void;
  setActivePanel: (panel: SketchpadPanelName | null) => void;
  setHighlightedIds: (ids: string[]) => void;
  setFocusedId: (id: string | null) => void;
  reset: () => void;
}

const INITIAL = {
  selectedIds: [] as string[],
  activePanel: null as SketchpadPanelName | null,
  highlightedIds: [] as string[],
  focusedId: null as string | null,
};

export const useSketchpadViewStore = create<SketchpadViewState>()((set) => ({
  ...INITIAL,
  setSelection: (selectedIds) => set({ selectedIds }),
  toggleSelection: (id) =>
    set((state) => ({
      selectedIds: state.selectedIds.includes(id)
        ? state.selectedIds.filter((current) => current !== id)
        : [...state.selectedIds, id],
    })),
  clearSelection: () => set({ selectedIds: [] }),
  setActivePanel: (activePanel) => set({ activePanel }),
  setHighlightedIds: (highlightedIds) => set({ highlightedIds }),
  setFocusedId: (focusedId) => set({ focusedId }),
  reset: () => set({ ...INITIAL }),
}));

export function useSketchpadSelectedIds(): string[] {
  return useSketchpadViewStore((state) => state.selectedIds);
}

export function useSketchpadHighlightedIds(): string[] {
  return useSketchpadViewStore((state) => state.highlightedIds);
}

export function selectSketchpadFragment(id: string | null): void {
  useSketchpadViewStore.getState().setSelection(id ? [id] : []);
}

export function resetSketchpadView(): void {
  useSketchpadViewStore.getState().reset();
}
