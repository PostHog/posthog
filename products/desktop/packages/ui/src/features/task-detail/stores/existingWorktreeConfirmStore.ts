import { create } from "zustand";

interface ExistingWorktreeConfirmState {
  isOpen: boolean;
  branch: string | null;
  worktreePath: string | null;
  resolve: ((confirmed: boolean) => void) | null;
}

interface ExistingWorktreeConfirmActions {
  /**
   * Opens the confirmation dialog for a branch that already has a worktree and
   * resolves to the user's choice. `true` reuses the existing worktree for the
   * task; `false` cancels.
   */
  confirm: (branch: string, worktreePath: string) => Promise<boolean>;
  accept: () => void;
  cancel: () => void;
}

type ExistingWorktreeConfirmStore = ExistingWorktreeConfirmState &
  ExistingWorktreeConfirmActions;

export const useExistingWorktreeConfirmStore =
  create<ExistingWorktreeConfirmStore>()((set, get) => ({
    isOpen: false,
    branch: null,
    worktreePath: null,
    resolve: null,

    confirm: (branch, worktreePath) =>
      new Promise<boolean>((resolve) => {
        // Resolve any dialog already waiting before replacing it.
        get().resolve?.(false);
        set({ isOpen: true, branch, worktreePath, resolve });
      }),

    accept: () => {
      get().resolve?.(true);
      set({ isOpen: false, branch: null, worktreePath: null, resolve: null });
    },

    cancel: () => {
      get().resolve?.(false);
      set({ isOpen: false, branch: null, worktreePath: null, resolve: null });
    },
  }));
