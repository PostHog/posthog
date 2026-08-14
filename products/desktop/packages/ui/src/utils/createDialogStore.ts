import { create } from "zustand";

export interface DialogStore {
  isOpen: boolean;
  open: () => void;
  close: () => void;
}

export function createDialogStore() {
  return create<DialogStore>((set) => ({
    isOpen: false,
    open: () => set({ isOpen: true }),
    close: () => set({ isOpen: false }),
  }));
}
