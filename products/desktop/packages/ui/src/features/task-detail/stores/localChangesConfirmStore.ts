import { create } from "zustand";

export type LocalChangesDialogAction =
  | "cancel"
  | "continue"
  | "stash-and-continue";

export interface LocalChanges {
  repoPath: string;
  stagedFiles: string[];
  unstagedFiles: string[];
  untrackedFiles: string[];
}

interface LocalChangesConfirmState extends LocalChanges {
  isOpen: boolean;
  resolve: ((action: LocalChangesDialogAction) => void) | null;
}

interface LocalChangesConfirmActions {
  confirm: (changes: LocalChanges) => Promise<LocalChangesDialogAction>;
  cancel: () => void;
  continue: () => void;
  stashAndContinue: () => void;
}

type LocalChangesConfirmStore = LocalChangesConfirmState &
  LocalChangesConfirmActions;

const initialState: LocalChangesConfirmState = {
  isOpen: false,
  repoPath: "",
  stagedFiles: [],
  unstagedFiles: [],
  untrackedFiles: [],
  resolve: null,
};

export const useLocalChangesConfirmStore = create<LocalChangesConfirmStore>()(
  (set, get) => {
    const resolve = (action: LocalChangesDialogAction): void => {
      get().resolve?.(action);
      set(initialState);
    };

    return {
      ...initialState,
      confirm: (changes) =>
        new Promise<LocalChangesDialogAction>((resolveCurrent) => {
          get().resolve?.("cancel");
          set({ ...changes, isOpen: true, resolve: resolveCurrent });
        }),
      cancel: () => resolve("cancel"),
      continue: () => resolve("continue"),
      stashAndContinue: () => resolve("stash-and-continue"),
    };
  },
);
