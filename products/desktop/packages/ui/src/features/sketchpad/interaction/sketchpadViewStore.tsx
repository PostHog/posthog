import {
  createContext,
  type ReactElement,
  type ReactNode,
  useContext,
  useState,
} from "react";
import { createStore, useStore } from "zustand";

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
}

const INITIAL = {
  selectedIds: [] as string[],
  activePanel: null as SketchpadPanelName | null,
  highlightedIds: [] as string[],
  focusedId: null as string | null,
};

const createSketchpadViewStore = () =>
  createStore<SketchpadViewState>()((set) => ({
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
  }));

export function useSketchpadSelectedIds(): string[] {
  return useSketchpadViewStore((state) => state.selectedIds);
}

export function useSketchpadHighlightedIds(): string[] {
  return useSketchpadViewStore((state) => state.highlightedIds);
}

const SketchpadViewContext = createContext<ReturnType<
  typeof createSketchpadViewStore
> | null>(null);

export function SketchpadViewProvider({
  children,
}: {
  children: ReactNode;
}): ReactElement {
  const [store] = useState(createSketchpadViewStore);
  return (
    <SketchpadViewContext.Provider value={store}>
      {children}
    </SketchpadViewContext.Provider>
  );
}

export function useSketchpadViewStore<T>(
  selector: (state: SketchpadViewState) => T,
): T {
  const store = useContext(SketchpadViewContext);
  if (!store) throw new Error("Sketchpad view requires a provider");
  return useStore(store, selector);
}
