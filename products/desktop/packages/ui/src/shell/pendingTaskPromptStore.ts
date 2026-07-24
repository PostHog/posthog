import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { logger } from "@posthog/ui/shell/logger";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

const log = logger.scope("pending-task-prompts");

const MAX_PENDING_PROMPTS = 20;

export interface PendingTaskPrompt {
  promptText: string;
  attachments: UserMessageAttachment[];
  createdAt: number;
}

export type PendingTaskPromptInput = Omit<PendingTaskPrompt, "createdAt">;

function capToNewest(
  byKey: Record<string, PendingTaskPrompt>,
): Record<string, PendingTaskPrompt> {
  const keys = Object.keys(byKey);
  if (keys.length <= MAX_PENDING_PROMPTS) {
    return byKey;
  }
  const keptKeys = keys
    .sort((a, b) => byKey[b].createdAt - byKey[a].createdAt)
    .slice(0, MAX_PENDING_PROMPTS);
  log.warn("Dropping oldest unrecovered prompts beyond cap", {
    dropped: keys.length - keptKeys.length,
  });
  const kept: Record<string, PendingTaskPrompt> = {};
  for (const key of keptKeys) {
    kept[key] = byKey[key];
  }
  return kept;
}

interface PendingTaskPromptStore {
  byKey: Record<string, PendingTaskPrompt>;
  _hasHydrated: boolean;
  setHasHydrated: (hydrated: boolean) => void;
  set: (key: string, prompt: PendingTaskPromptInput) => void;
  get: (key: string) => PendingTaskPrompt | undefined;
  move: (fromKey: string, toKey: string) => void;
  clear: (key: string) => void;
}

export const usePendingTaskPromptStore = create<PendingTaskPromptStore>()(
  persist(
    (set, get) => ({
      byKey: {},
      _hasHydrated: false,
      setHasHydrated: (hydrated) => set({ _hasHydrated: hydrated }),
      set: (key, prompt) =>
        set((state) => ({
          byKey: capToNewest({
            ...state.byKey,
            [key]: { ...prompt, createdAt: Date.now() },
          }),
        })),
      get: (key) => get().byKey[key],
      move: (fromKey, toKey) => {
        if (fromKey === toKey) {
          return;
        }
        set((state) => {
          const entry = state.byKey[fromKey];
          if (!entry) {
            return state;
          }
          const { [fromKey]: _removed, ...rest } = state.byKey;
          return { byKey: { ...rest, [toKey]: entry } };
        });
      },
      clear: (key) =>
        set((state) => {
          if (!(key in state.byKey)) {
            return state;
          }
          const { [key]: _removed, ...rest } = state.byKey;
          return { byKey: rest };
        }),
    }),
    {
      name: "pending-task-prompts",
      storage: electronStorage,
      partialize: (state) => ({ byKey: state.byKey }),
      onRehydrateStorage: () => (state, error) => {
        if (error) {
          usePendingTaskPromptStore.getState().setHasHydrated(true);
        } else {
          state?.setHasHydrated(true);
        }
      },
    },
  ),
);

export interface RecoverablePendingPrompt {
  key: string;
  prompt: PendingTaskPrompt;
}

export const pendingTaskPromptStoreApi = {
  set: (key: string, prompt: PendingTaskPromptInput) =>
    usePendingTaskPromptStore.getState().set(key, prompt),
  get: (key: string) => usePendingTaskPromptStore.getState().get(key),
  move: (fromKey: string, toKey: string) =>
    usePendingTaskPromptStore.getState().move(fromKey, toKey),
  clear: (key: string) => usePendingTaskPromptStore.getState().clear(key),
  getAllNewestFirst: (): RecoverablePendingPrompt[] =>
    Object.entries(usePendingTaskPromptStore.getState().byKey)
      .map(([key, prompt]) => ({ key, prompt }))
      .sort((a, b) => b.prompt.createdAt - a.prompt.createdAt),
  whenHydrated: (): Promise<void> => {
    if (usePendingTaskPromptStore.getState()._hasHydrated) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      const unsubscribe = usePendingTaskPromptStore.subscribe((state) => {
        if (state._hasHydrated) {
          unsubscribe();
          resolve();
        }
      });
    });
  },
};

export function usePendingTaskPrompt(
  key: string | undefined,
): PendingTaskPrompt | undefined {
  return usePendingTaskPromptStore((state) =>
    key ? state.byKey[key] : undefined,
  );
}
