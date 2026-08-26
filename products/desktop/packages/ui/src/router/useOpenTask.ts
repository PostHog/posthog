import { resolveService, resolveServiceOptional } from "@posthog/di/container";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { navigateBrowserTab } from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
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
 * channel), navigation targets the channel-organized view under /spaces,
 * keeping the channels chrome; otherwise it targets /tasks/$taskId. Every
 * other side effect is identical — channel tasks still need workspace
 * provisioning so TaskDetail resolves a cwd.
 *
 * Replaces the old `navigationStore.navigateToTask` action.
 */
export async function openTask(
  task: Task,
  opts?: { channelId?: string; tabId?: string | null },
): Promise<void> {
  // Seed the detail cache so the route loader resolves from cache and never
  // fetches — critical for optimistic/local/cloud-pending tasks that the API
  // can't yet return, which would otherwise hang the route in its pending state.
  resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT).setQueryData(
    taskDetailQuery(task.id).queryKey,
    task,
  );
  const href = opts?.channelId
    ? `/spaces/${opts.channelId}/tasks/${task.id}`
    : `/tasks/${task.id}`;
  const navigationResult = navigateBrowserTab(
    opts?.tabId ?? null,
    {
      href,
      title: task.title,
      taskId: task.id,
      channelId: opts?.channelId ?? null,
    },
    () => {
      if (opts?.channelId) {
        nav.navigateToChannelTask(opts.channelId, task.id);
      } else {
        nav.navigateToTaskDetail(task.id);
      }
    },
  );
  if (navigationResult === "active") {
    setActiveTaskContext(task);
    track(ANALYTICS_EVENTS.TASK_VIEWED, { task_id: task.id });
  }

  const result = await resolveServiceOptional<NavigationTaskBinder>(
    NAVIGATION_TASK_BINDER,
  )?.ensureWorkspaceForTask(task);
  const staleFolderId = result?.staleFolderId;
  if (staleFolderId) {
    navigateBrowserTab(
      opts?.tabId ?? null,
      {
        href: `/folders/${staleFolderId}`,
        title: "Folder settings",
      },
      () => nav.navigateToFolderSettings(staleFolderId),
    );
  }
}

/** React hook wrapper returning a stable `openTask` callback. */
export function useOpenTask(): (task: Task) => Promise<void> {
  return useCallback(openTask, []);
}

export interface TaskInputNavigationOptions {
  folderId?: string;
  /**
   * `owner/repo` the picked sidebar group stands for. Cloud-only groups have no
   * registered folder, so this is the only thing the new-task screen can prefill
   * its repo from. Unlike `initialCloudRepository` it does not force cloud mode.
   */
  folderRepository?: string;
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
  /** Ignore whichever space is scoped and file the task nowhere. */
  unscoped?: boolean;
  /**
   * Create inside this channel. Callers that already know the channel should
   * say so rather than relying on the sidebar's scope agreeing with them — and
   * routing through here is what clears any stale prefill.
   */
  channelId?: string;
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

  // The folder prefill counts as transient state: each "+" click must get a
  // fresh requestId so re-picking the same group re-applies the prefill.
  const hasTransientState =
    !!options.folderId ||
    !!options.folderRepository ||
    !!options.initialPrompt ||
    !!options.initialCloudRepository ||
    !!options.initialModel ||
    !!options.initialMode ||
    !!options.reportAssociation;

  useTaskInputPrefillStore.setState({
    prefill: {
      folderId: options.folderId,
      folderRepository: options.folderRepository,
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
  // In the channels layout every entry point (⌘N, the command menu, the "+")
  // creates inside the channel you're in. A current channel only exists while
  // that layout is on (ChannelsSidebar), so this needs no flag of its own.
  // Precedence: an explicit channel wins; asking for Code explicitly opts out
  // of channel scoping; otherwise the scoped channel decides.
  const channelId =
    options.channelId ??
    (options.unscoped
      ? null
      : useCurrentChannelStore.getState().currentChannelId);
  if (channelId) nav.navigateToChannelNewTask(channelId);
  else nav.navigateToNewTask();
}

export function useOpenTaskInput(): typeof openTaskInput {
  return useCallback(openTaskInput, []);
}
