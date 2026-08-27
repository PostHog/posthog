import type { PendingPromptInterruptReason } from "@posthog/core/tasks/pendingPrompts";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface PendingTaskPrompt {
  promptText: string;
  attachments: UserMessageAttachment[];
  /**
   * Serialized editor content (chips + attachments) so recovery restores the
   * full prompt, not just its plain text. Absent on records written before this
   * field existed; recovery falls back to promptText for those.
   */
  contentXml?: string;
  /**
   * Set when task setup failed and left the prompt unsent. Presence flips the
   * pending view from "starting" to the recoverable interrupted state. Cleared
   * only by delivery (success) or the user discarding the prompt.
   */
  interruptReason?: PendingPromptInterruptReason;
  /**
   * Space the prompt was submitted in, so recovery reopens it there instead of
   * whatever space is current. Absent means it was submitted unscoped.
   */
  channelId?: string;
  createdAt: number;
}

export type PendingTaskPromptInput = Omit<
  PendingTaskPrompt,
  "createdAt" | "interruptReason"
>;

interface PendingTaskPromptStore {
  byKey: Record<string, PendingTaskPrompt>;
  _hasHydrated: boolean;
  setHasHydrated: (hydrated: boolean) => void;
  set: (key: string, prompt: PendingTaskPromptInput) => void;
  get: (key: string) => PendingTaskPrompt | undefined;
  move: (fromKey: string, toKey: string) => void;
  markInterrupted: (key: string, reason: PendingPromptInterruptReason) => void;
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
      markInterrupted: (key, reason) =>
        set((state) => {
          const entry = state.byKey[key];
          if (!entry) {
            return state;
          }
          return {
            byKey: {
              ...state.byKey,
              [key]: { ...entry, interruptReason: reason },
            },
          };
        }),
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
  markInterrupted: (key: string, reason: PendingPromptInterruptReason) =>
    usePendingTaskPromptStore.getState().markInterrupted(key, reason),
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
