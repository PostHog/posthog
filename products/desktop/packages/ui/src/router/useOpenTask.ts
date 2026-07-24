import { resolveService, resolveServiceOptional } from "@posthog/di/container";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  NAVIGATION_TASK_BINDER,
  type NavigationTaskBinder,
} from "@posthog/ui/features/navigation/taskBinder";
import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { setActiveTaskContext, track } from "@posthog/ui/shell/analytics";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import { useCallback } from "react";
import * as nav from "./navigationBridge";

/**
 * Opens a task: navigates to its detail route and ensures a workspace exists.
 * Workspace binding is delegated to the host-provided NavigationTaskBinder (the
 * refactor's abstraction over folder/workspace registration); if it reports a
 * stale folder, we redirect to folder settings.
 *
 * When `opts.channelId` is provided (the task is filed to a Project Bluebird
 * channel), navigation targets the channel-organized view under /website,
 * keeping the channels chrome; otherwise it targets /code/tasks/$taskId. Every
 * other side effect is identical — channel tasks still need workspace
 * provisioning so TaskDetail resolves a cwd.
 *
 * Replaces the old `navigationStore.navigateToTask` action.
 */
export async function openTask(
  task: Task,
  opts?: { channelId?: string },
): Promise<void> {
  // Seed the detail cache so the route loader resolves from cache and never
  // fetches — critical for optimistic/local/cloud-pending tasks that the API
  // can't yet return, which would otherwise hang the route in its pending state.
  resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT).setQueryData(
    taskDetailQuery(task.id).queryKey,
    task,
  );
  if (opts?.channelId) {
    nav.navigateToChannelTask(opts.channelId, task.id);
  } else {
    nav.navigateToTaskDetail(task.id);
  }
  setActiveTaskContext(task);
  track(ANALYTICS_EVENTS.TASK_VIEWED, { task_id: task.id });

  const result = await resolveServiceOptional<NavigationTaskBinder>(
    NAVIGATION_TASK_BINDER,
  )?.ensureWorkspaceForTask(task);
  if (result?.staleFolderId) {
    nav.navigateToFolderSettings(result.staleFolderId);
  }
}

/** React hook wrapper returning a stable `openTask` callback. */
export function useOpenTask(): (task: Task) => Promise<void> {
  return useCallback(openTask, []);
}

export interface TaskInputNavigationOptions {
  folderId?: string;
  initialPrompt?: string;
  initialCloudRepository?: string;
  initialModel?: string;
  initialMode?: string;
  /**
   * Environment ("local" | "cloud") of the folder's most recent visible run,
   * used to prefill the workspace mode when starting a task scoped to a folder.
   */
  folderRunEnvironment?: "local" | "cloud";
  reportAssociation?: { reportId: string; title: string };
  // Which space's new-task screen to open. Both render the same TaskInput; the
  // channels variant keeps the channels chrome instead of switching to Code.
  space?: "code" | "website";
}

/**
 * Navigate to the new-task screen, optionally with prefill (initial prompt,
 * report association, cloud repository, etc.). Replaces the old
 * `navigationStore.navigateToTaskInput` action.
 */
export function openTaskInput(
  folderIdOrOptions?: string | TaskInputNavigationOptions,
): void {
  const options =
    typeof folderIdOrOptions === "string"
      ? { folderId: folderIdOrOptions }
      : (folderIdOrOptions ?? {});

  // folderId counts as transient state: each "+" click must get a fresh
  // requestId so re-picking the same folder re-applies the prefill.
  const hasTransientState =
    !!options.folderId ||
    !!options.initialPrompt ||
    !!options.initialCloudRepository ||
    !!options.initialModel ||
    !!options.initialMode ||
    !!options.reportAssociation;

  useTaskInputPrefillStore.setState({
    prefill: {
      folderId: options.folderId,
      initialPrompt: options.initialPrompt,
      initialCloudRepository: options.initialCloudRepository,
      initialModel: options.initialModel,
      initialMode: options.initialMode,
      folderRunEnvironment: options.folderRunEnvironment,
      reportAssociation: options.reportAssociation,
      requestId: hasTransientState
        ? (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`)
        : undefined,
    },
  });
  if (options.space === "website") {
    nav.navigateToWebsiteNew();
  } else {
    nav.navigateToCode();
  }
}

export function useOpenTaskInput(): typeof openTaskInput {
  return useCallback(openTaskInput, []);
}
