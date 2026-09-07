import { create } from "zustand";

interface SettingsPageContext {
  repoPath?: string;
}

interface SettingsPageState {
  context: SettingsPageContext;
  initialAction: string | null;
  formMode: boolean;
}

interface SettingsPageActions {
  setContext: (context: SettingsPageContext) => void;
  clearContext: () => void;
  setInitialAction: (action: string | null) => void;
  consumeInitialAction: () => string | null;
  setFormMode: (formMode: boolean) => void;
  reset: () => void;
}

type SettingsPageStore = SettingsPageState & SettingsPageActions;

/**
 * UI-only state for the Settings page. Holds per-open context (e.g. which
 * repo to focus on the worktrees page), a one-shot action (e.g. "open the
 * create-environment form on entry"), and the section's form/list mode.
 *
 * The active category is NOT here — it lives in the URL
 * (`/settings/$category`) and is read via `Route.useParams()`.
 */
export const useSettingsPageStore = create<SettingsPageStore>()((set, get) => ({
  context: {},
  initialAction: null,
  formMode: false,
  setContext: (context) => set({ context }),
  clearContext: () => set({ context: {} }),
  setInitialAction: (action) => set({ initialAction: action }),
  consumeInitialAction: () => {
    const action = get().initialAction;
    if (action) set({ initialAction: null });
    return action;
  },
  setFormMode: (formMode) => set({ formMode }),
  reset: () => set({ context: {}, initialAction: null, formMode: false }),
}));
