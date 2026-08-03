import {
  removeScrollback,
  removeScrollbackForTask,
} from "@posthog/ui/features/terminal/terminalScrollback";
import { create } from "zustand";

export interface TerminalState {
  sessionId: string | null;
  processName: string | null;
}

interface TerminalStoreState {
  terminalStates: Record<string, TerminalState>;
  setSessionId: (key: string, sessionId: string) => void;
  setProcessName: (key: string, processName: string | null) => void;
  clearTerminalState: (key: string) => void;
  clearTerminalStatesForTask: (taskId: string) => void;
}

export const useTerminalStore = create<TerminalStoreState>()((set) => ({
  terminalStates: {},

  setSessionId: (key: string, sessionId: string) => {
    set((prev) => ({
      terminalStates: {
        ...prev.terminalStates,
        [key]: {
          ...prev.terminalStates[key],
          processName: prev.terminalStates[key]?.processName ?? null,
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
          sessionId: prev.terminalStates[key]?.sessionId ?? null,
          processName,
        },
      },
    }));
  },

  clearTerminalState: (key: string) => {
    removeScrollback(key);
    set((prev) => {
      const newStates = { ...prev.terminalStates };
      delete newStates[key];
      return { terminalStates: newStates };
    });
  },

  clearTerminalStatesForTask: (taskId: string) => {
    removeScrollbackForTask(taskId);
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
}));
