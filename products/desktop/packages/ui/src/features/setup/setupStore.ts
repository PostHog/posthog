import type {
  ActivityEntry,
  SetupStoreState,
} from "@posthog/core/setup/setupState";
import {
  DEFAULT_DISCOVERY,
  dropAgentTasksForRepo,
  EMPTY_FEED,
  INITIAL_SETUP_STATE,
  isTaskForRepo,
  migrateSetupState,
  partializeSetupState,
  pushEntry,
  updateDiscovery,
  updateEnricher,
} from "@posthog/core/setup/setupState";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import { logger } from "@posthog/ui/shell/logger";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type {
  ActivityEntry,
  AgentFeedState,
  RepoDiscoveryState,
  RepoEnricherState,
  SetupStoreState,
} from "@posthog/core/setup/setupState";
export {
  isTaskForRepo,
  selectRepoDiscovery,
  selectRepoEnricher,
} from "@posthog/core/setup/setupState";

const log = logger.scope("setup-store");

interface SetupStoreActions {
  startDiscovery: (repoPath: string, taskId: string, taskRunId: string) => void;
  completeDiscovery: (repoPath: string, tasks: DiscoveredTask[]) => void;
  failDiscovery: (repoPath: string, message?: string) => void;
  resetDiscovery: (repoPath: string) => void;
  startEnrichment: (repoPath: string) => void;
  completeEnrichment: (repoPath: string) => void;
  failEnrichment: (repoPath: string) => void;
  removeDiscoveredTask: (taskId: string, repoPath: string | null) => void;
  addEnricherSuggestionIfMissing: (task: DiscoveredTask) => void;
  pushDiscoveryActivity: (repoPath: string, entry: ActivityEntry) => void;
  resetSetup: () => void;
}

type SetupStore = SetupStoreState & SetupStoreActions;

export const useSetupStore = create<SetupStore>()(
  persist(
    (set) => ({
      ...INITIAL_SETUP_STATE,

      startDiscovery: (repoPath, taskId, taskRunId) => {
        log.info("Discovery started", { repoPath, taskId, taskRunId });
        set((state) => ({
          discoveredTasks: dropAgentTasksForRepo(
            state.discoveredTasks,
            repoPath,
          ),
          discoveryByRepo: updateDiscovery(state, repoPath, {
            status: "running",
            taskId,
            taskRunId,
            feed: EMPTY_FEED,
            error: null,
          }),
        }));
      },

      completeDiscovery: (repoPath, tasks) => {
        log.info("Discovery completed", {
          repoPath,
          taskCount: tasks.length,
        });
        set((state) => {
          const cleaned = dropAgentTasksForRepo(
            state.discoveredTasks,
            repoPath,
          );
          const agent = tasks.map((t) => ({
            ...t,
            source: "agent" as const,
            repoPath: t.repoPath ?? repoPath,
          }));
          return {
            discoveredTasks: [...cleaned, ...agent],
            discoveryByRepo: updateDiscovery(state, repoPath, {
              status: "done",
              error: null,
            }),
          };
        });
      },

      failDiscovery: (repoPath, message) => {
        log.warn("Discovery failed", { repoPath, message });
        set((state) => ({
          discoveryByRepo: updateDiscovery(state, repoPath, {
            status: "error",
            error: message ?? null,
          }),
        }));
      },

      resetDiscovery: (repoPath) => {
        log.info("Discovery reset", { repoPath });
        set((state) => ({
          discoveredTasks: dropAgentTasksForRepo(
            state.discoveredTasks,
            repoPath,
          ),
          discoveryByRepo: updateDiscovery(state, repoPath, {
            status: "idle",
            taskId: null,
            taskRunId: null,
            feed: EMPTY_FEED,
            error: null,
          }),
        }));
      },

      startEnrichment: (repoPath) => {
        set((state) => ({
          enricherByRepo: updateEnricher(state, repoPath, {
            status: "running",
          }),
        }));
      },

      completeEnrichment: (repoPath) => {
        set((state) => ({
          enricherByRepo: updateEnricher(state, repoPath, { status: "done" }),
        }));
      },

      failEnrichment: (repoPath) => {
        set((state) => ({
          enricherByRepo: updateEnricher(state, repoPath, { status: "error" }),
        }));
      },

      removeDiscoveredTask: (taskId, repoPath) => {
        set((state) => ({
          discoveredTasks: state.discoveredTasks.filter(
            (t) => !(t.id === taskId && isTaskForRepo(t, repoPath)),
          ),
        }));
      },

      addEnricherSuggestionIfMissing: (task) => {
        set((state) => {
          const repoTask = { ...task, source: "enricher" as const };
          if (
            state.discoveredTasks.some(
              (t) => t.id === repoTask.id && t.repoPath === repoTask.repoPath,
            )
          ) {
            return state;
          }
          return {
            discoveredTasks: [repoTask, ...state.discoveredTasks],
          };
        });
      },

      pushDiscoveryActivity: (repoPath, entry) => {
        set((state) => {
          const prev = state.discoveryByRepo[repoPath] ?? DEFAULT_DISCOVERY;
          return {
            discoveryByRepo: updateDiscovery(state, repoPath, {
              feed: pushEntry(prev.feed, entry),
            }),
          };
        });
      },

      resetSetup: () => {
        log.info("Setup state reset");
        set({ ...INITIAL_SETUP_STATE });
      },
    }),
    {
      name: "setup-store",
      version: 2,
      migrate: migrateSetupState,
      partialize: (state) => partializeSetupState(state),
    },
  ),
);
