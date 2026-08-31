import { create } from "zustand";

/**
 * View state for the restart-interrupt flow: the confirm dialog, the armed
 * "restart when agents finish" wait, and the install action both resolve to.
 * `open` keeps an armed wait, so reopening the dialog does not silently
 * disarm it; only `clear` (cancel/dismiss) does.
 */
interface UpdateInterruptState {
  isOpen: boolean;
  waitingForIdle: boolean;
  runInstall: (() => void) | null;
  open: (runInstall: () => void) => void;
  wait: () => void;
  clear: () => void;
}

export const useUpdateInterruptStore = create<UpdateInterruptState>((set) => ({
  isOpen: false,
  waitingForIdle: false,
  runInstall: null,
  open: (runInstall) => set({ isOpen: true, runInstall }),
  wait: () => set({ isOpen: false, waitingForIdle: true }),
  clear: () => set({ isOpen: false, waitingForIdle: false, runInstall: null }),
}));
