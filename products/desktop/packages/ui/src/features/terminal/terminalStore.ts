import { create } from "zustand";
import { persist } from "zustand/middleware";
import { terminalManager } from "./TerminalManager";

export interface TerminalState {
  serializedState: string | null;
  sessionId: string | null;
  processName: string | null;
}

interface TerminalStoreState {
  terminalStates: Record<string, TerminalState>;
  getTerminalState: (key: string) => TerminalState | undefined;
  setSerializedState: (key: string, state: string) => void;
  setSessionId: (key: string, sessionId: string) => void;
  setProcessName: (key: string, processName: string | null) => void;
  clearTerminalState: (key: string) => void;
  clearTerminalStatesForTask: (taskId: string) => void;
}

type PersistedTerminalStoreState = {
  terminalStates: Record<
    string,
    {
      serializedState: string | null;
      sessionId: null;
    }
  >;
};

const DEFAULT_TERMINAL_STATE: TerminalState = {
  serializedState: null,
  sessionId: null,
  processName: null,
};

export function clearPersistedSessionIds(persistedState: unknown) {
  if (!persistedState || typeof persistedState !== "object") {
    return persistedState;
  }

  const state = persistedState as {
    terminalStates?: Record<string, Partial<TerminalState>>;
  };

  if (!state.terminalStates || typeof state.terminalStates !== "object") {
    return persistedState;
  }

  return {
    ...state,
    terminalStates: Object.fromEntries(
      Object.entries(state.terminalStates).map(([key, value]) => [
        key,
        {
          ...value,
          sessionId: null,
        },
      ]),
    ),
  };
}

export const useTerminalStore = create<TerminalStoreState>()(
  persist(
    (set, get) => ({
      terminalStates: {},

      getTerminalState: (key: string) => {
        return get().terminalStates[key] || DEFAULT_TERMINAL_STATE;
      },

      setSerializedState: (key: string, state: string) => {
        set((prev) => ({
          terminalStates: {
            ...prev.terminalStates,
            [key]: {
              ...prev.terminalStates[key],
              serializedState: state,
            },
          },
        }));
      },

      setSessionId: (key: string, sessionId: string) => {
        set((prev) => ({
          terminalStates: {
            ...prev.terminalStates,
            [key]: {
              ...prev.terminalStates[key],
              sessionId,
            },
          },
        }));
      },

      setProcessName: (key: string, processName: string | null) => {
        set((prev) => ({
          terminalStates: {
            ...prev.terminalStates,
            [key]: {
              ...prev.terminalStates[key],
              processName,
            },
          },
        }));
      },

      clearTerminalState: (key: string) => {
        set((prev) => {
          const newStates = { ...prev.terminalStates };
          delete newStates[key];
          return { terminalStates: newStates };
        });
      },

      clearTerminalStatesForTask: (taskId: string) => {
        set((prev) => {
          const newStates = { ...prev.terminalStates };
          for (const key of Object.keys(newStates)) {
            if (key === taskId || key.startsWith(`${taskId}-`)) {
              delete newStates[key];
            }
          }
          return { terminalStates: newStates };
        });
      },
    }),
    {
      name: "terminal-store",
      version: 1,
      migrate: (persistedState) =>
        clearPersistedSessionIds(persistedState) as PersistedTerminalStoreState,
      partialize: (state): PersistedTerminalStoreState => ({
        terminalStates: Object.fromEntries(
          Object.entries(state.terminalStates).map(([k, v]) => [
            k,
            { serializedState: v.serializedState, sessionId: null },
          ]),
        ),
      }),
    },
  ),
);

terminalManager.on("stateChange", ({ persistenceKey, serializedState }) => {
  useTerminalStore
    .getState()
    .setSerializedState(persistenceKey, serializedState);
});
