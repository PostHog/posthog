import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface PendingTaskPrompt {
  promptText: string;
  attachments: UserMessageAttachment[];
  createdAt: number;
}

export type PendingTaskPromptInput = Omit<PendingTaskPrompt, "createdAt">;

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
          byKey: capPendingPrompts({
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
    listPendingPromptsNewestFirst(usePendingTaskPromptStore.getState().byKey),
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

export function generatePendingTaskKey(): string {
  return buildPendingPromptKey(
    globalThis.crypto?.randomUUID?.() ?? null,
    Date.now(),
    Math.random().toString(36).slice(2, 10),
  );
}

export function usePendingTaskPrompt(
  key: string | undefined,
): PendingTaskPrompt | undefined {
  return usePendingTaskPromptStore((state) =>
    key ? state.byKey[key] : undefined,
  );
}

import {
  buildPendingPromptKey,
  capPendingPrompts,
  listPendingPromptsNewestFirst,
} from "@posthog/core/tasks/pendingPrompts";
