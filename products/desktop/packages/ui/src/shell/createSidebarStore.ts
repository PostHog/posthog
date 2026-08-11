import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface SidebarStoreState {
  open: boolean;
  width: number;
  isResizing: boolean;
}

export interface SidebarStoreActions {
  setOpen: (open: boolean) => void;
  toggle: () => void;
  setWidth: (width: number) => void;
  setIsResizing: (isResizing: boolean) => void;
}

export type SidebarStore = SidebarStoreState & SidebarStoreActions;

interface CreateSidebarStoreOptions {
  name: string;
  defaultWidth: number;
  defaultOpen?: boolean;
  /**
   * Floor for live sets and rehydrated values alike — without it a width
   * persisted under an older, lower minimum survives below the new one.
   */
  minWidth?: number;
}

export function createSidebarStore(options: CreateSidebarStoreOptions) {
  const { name, defaultWidth, defaultOpen = true, minWidth } = options;
  const clampWidth = (width: number) =>
    minWidth === undefined ? width : Math.max(minWidth, width);

  return create<SidebarStore>()(
    persist(
      (set) => ({
        open: defaultOpen,
        width: clampWidth(defaultWidth),
        isResizing: false,
        setOpen: (open) => set({ open }),
        toggle: () => set((state) => ({ open: !state.open })),
        setWidth: (width) => set({ width: clampWidth(width) }),
        setIsResizing: (isResizing) => set({ isResizing }),
      }),
      {
        name,
        partialize: (state) => ({
          open: state.open,
          width: state.width,
        }),
        merge: (persisted, current) => {
          const stored = (persisted ?? {}) as Partial<
            Pick<SidebarStoreState, "open" | "width">
          >;
          return {
            ...current,
            open: stored.open ?? current.open,
            width: clampWidth(stored.width ?? current.width),
          };
        },
      },
    ),
  );
}
