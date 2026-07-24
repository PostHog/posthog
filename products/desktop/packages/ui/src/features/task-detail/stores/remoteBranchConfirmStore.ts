import { create } from "zustand";

interface RemoteBranchConfirmState {
  isOpen: boolean;
  branch: string | null;
  resolve: ((confirmed: boolean) => void) | null;
}

interface RemoteBranchConfirmActions {
  /**
   * Opens the confirmation dialog for a remote-only branch and resolves to the
   * user's choice. `true` means check the branch out locally; `false` cancels.
   */
  confirm: (branch: string) => Promise<boolean>;
  accept: () => void;
  cancel: () => void;
}

type RemoteBranchConfirmStore = RemoteBranchConfirmState &
  RemoteBranchConfirmActions;

export const useRemoteBranchConfirmStore = create<RemoteBranchConfirmStore>()(
  (set, get) => ({
    isOpen: false,
    branch: null,
    resolve: null,

    confirm: (branch) =>
      new Promise<boolean>((resolve) => {
        // Resolve any dialog already waiting before replacing it.
        get().resolve?.(false);
        set({ isOpen: true, branch, resolve });
      }),

    accept: () => {
      get().resolve?.(true);
      set({ isOpen: false, branch: null, resolve: null });
    },

    cancel: () => {
      get().resolve?.(false);
      set({ isOpen: false, branch: null, resolve: null });
    },
  }),
);
