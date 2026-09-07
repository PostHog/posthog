import type { TaskCreationEffects } from "@posthog/core/task-detail/taskCreationEffects";
import { resolveService } from "@posthog/di/container";
import type {
  TaskCreationInput,
  TaskCreationOutput,
  Workspace,
} from "@posthog/shared";
import type { Task, TaskRun } from "@posthog/shared/domain-types";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "../../shell/queryClient";
import { useDraftStore } from "../message-editor/draftStore";
import { useSettingsStore } from "../settings/settingsStore";
import { taskKeys } from "../tasks/taskKeys";
import { WORKSPACE_QUERY_KEY } from "../workspace/identifiers";

function queryClient(): ImperativeQueryClient {
  return resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT);
}

export const taskCreationEffects: TaskCreationEffects = {
  onWorkspaceCreated(output: TaskCreationOutput): void {
    if (!output.workspace) return;
    const workspace = output.workspace;
    const client = queryClient();
    client.setQueriesData<Record<string, Workspace>>(
      { queryKey: WORKSPACE_QUERY_KEY },
      (old) => ({ ...old, [output.task.id]: workspace }),
    );
    void client.invalidateQueries({ queryKey: WORKSPACE_QUERY_KEY });
  },

  onRunResumed(taskId: string, run: TaskRun): void {
    const client = queryClient();
    client.setQueryData<Task>(taskKeys.detail(taskId), (task) =>
      task ? { ...task, latest_run: run } : task,
    );
    client.setQueriesData<Task[]>({ queryKey: taskKeys.lists() }, (tasks) =>
      tasks?.map((task) =>
        task.id === taskId ? { ...task, latest_run: run } : task,
      ),
    );
    void client.invalidateQueries({ queryKey: taskKeys.allSummaries() });
  },

  onCreateSuccess(output: TaskCreationOutput, input?: TaskCreationInput): void {
    if (!input) return;

    const settings = useSettingsStore.getState();
    const draftStore = useDraftStore.getState();

    const workspaceMode =
      input.workspaceMode ?? output.workspace?.mode ?? "local";

    settings.setLastUsedWorkspaceMode(workspaceMode);

    if (workspaceMode === "cloud") {
      settings.setLastUsedRunMode("cloud");
    } else {
      settings.setLastUsedRunMode("local");
      settings.setLastUsedLocalWorkspaceMode(
        workspaceMode as "worktree" | "local",
      );
    }

    draftStore.actions.setDraft("task-input", null);
  },
};
