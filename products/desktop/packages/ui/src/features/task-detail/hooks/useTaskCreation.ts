import { partitionLocalMcpServersForRun } from "@posthog/core/local-mcp/localMcpImport";
import {
  getErrorTitle,
  prepareTaskInput,
} from "@posthog/core/task-detail/taskInput";
import {
  isUsageLimitResult,
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import type { HostTrpcClient } from "@posthog/host-router/client";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import {
  type Adapter,
  type AgentRuntime,
  ANALYTICS_EVENTS,
  PROJECT_BLUEBIRD_FLAG,
  type TaskCreationInput,
  type WorkspaceMode,
} from "@posthog/shared";
import type { ExecutionMode, Task } from "@posthog/shared/domain-types";
import {
  getCurrentBrowserTabId,
  navigateBrowserTab,
} from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useTaskRepositoryDraftStore } from "@posthog/ui/features/canvas/stores/taskRepositoryDraftStore";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { waitForComposerExit } from "@posthog/ui/features/task-detail/newTaskComposerTransition";
import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { navigateToTaskPending } from "@posthog/ui/router/navigationBridge";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useConnectivity } from "../../../hooks/useConnectivity";
import { toast } from "../../../primitives/toast";
import { track } from "../../../shell/analytics";
import { logger } from "../../../shell/logger";
import {
  generatePendingTaskKey,
  pendingTaskPromptStoreApi,
} from "../../../shell/pendingTaskPromptStore";
import { titleAttachmentStoreApi } from "../../../shell/titleAttachmentStore";
import { useAuthStateValue } from "../../auth/store";
import { assertCloudUsageAvailable } from "../../billing/preflightCloudUsage";
import { useUsageLimitStore } from "../../billing/usageLimitStore";
import { useLocalMcpCloudServers } from "../../local-mcp/useLocalMcpCloudServers";
import {
  contentToPlainText,
  contentToXml,
  type EditorContent,
  extractFilePaths,
} from "../../message-editor/content";
import { useDraftStore } from "../../message-editor/draftStore";
import { useTaskInputHistoryStore } from "../../message-editor/taskInputHistoryStore";
import type { EditorHandle } from "../../message-editor/types";
import { toastError } from "../../notifications/errorDetails";
import { useProvisioningStore } from "../../provisioning/store";
import {
  getEffectiveCustomInstructions,
  useSettingsStore,
} from "../../settings/settingsStore";
import { useCreateTask } from "../../tasks/useTaskCrudMutations";
import { useTasks } from "../../tasks/useTasks";
import { useTourStore } from "../../tour/tourStore";
import { createFirstTaskTour } from "../../tour/tours/createFirstTaskTour";
import { useExistingWorktreeConfirmStore } from "../stores/existingWorktreeConfirmStore";
import { useRemoteBranchConfirmStore } from "../stores/remoteBranchConfirmStore";
import { restoreTaskInputTab } from "../taskInputTab";

const log = logger.scope("task-creation");

interface UseTaskCreationOptions {
  editorRef: React.RefObject<EditorHandle | null>;
  /** Draft-store session id for the editor; cleared on successful creation. */
  sessionId: string;
  selectedDirectory: string;
  selectedRepository?: string | null;
  repositories?: string[];
  githubIntegrationId?: number;
  githubUserIntegrationId?: string;
  workspaceMode: WorkspaceMode;
  branch?: string | null;
  editorIsEmpty: boolean;
  executionMode?: ExecutionMode;
  adapter?: Adapter;
  runtime?: AgentRuntime;
  model?: string;
  reasoningLevel?: string;
  contextWindow?: "200k" | "1m";
  fastMode?: boolean;
  environmentId?: string | null;
  sandboxEnvironmentId?: string;
  customImageId?: string;
  signalReportId?: string;
  channelContext?: string;
  channelContextPath?: string;
  submissionBlocked?: boolean;
  channelName?: string;
  /** Backend channel UUID the created task is owned by (its feed home). */
  channelId?: string;
  /**
   * Desktop file-system folder id that owns the channel's CONTEXT.md (the
   * `/spaces/$channelId` id, distinct from the feed `channelId`). Lets the
   * injected context address CONTEXT.md upkeep writes by a stable id.
   */
  channelContextId?: string;
  /**
   * Channels "generic chat box" mode: drop the repo/branch requirement so a
   * task can be submitted without picking a repo. The agent decides at runtime
   * whether it needs one and attaches it lazily.
   */
  allowNoRepo?: boolean;
  onTaskCreated?: (task: Task) => void;
  /**
   * Side effect run with the created task in addition to (not instead of)
   * the default open/navigation behavior — unlike onTaskCreated, providing
   * this does not suppress the pending-task view.
   */
  onTaskCreatedEffect?: (task: Task) => void;
}

interface UseTaskCreationReturn {
  isCreatingTask: boolean;
  /** The task is on its way; the composer fades out before the chat replaces it. */
  isExitingComposer: boolean;
  canSubmit: boolean;
  handleSubmit: (contentOverride?: EditorContent) => Promise<boolean>;
  additionalDirectories: string[];
  setAdditionalDirectories: (next: string[]) => void;
}

async function trackTaskCreated(
  input: TaskCreationInput,
  selectedDirectory: string,
  hostClient: HostTrpcClient,
): Promise<void> {
  try {
    const workspaceMode = input.workspaceMode ?? "local";

    let usesWorktreeLink: boolean | undefined;
    let usesWorktreeInclude: boolean | undefined;
    if (workspaceMode === "worktree" && selectedDirectory) {
      try {
        const usage = await hostClient.workspace.getWorktreeFileUsage.query({
          mainRepoPath: selectedDirectory,
        });
        usesWorktreeLink = usage.usesWorktreeLink;
        usesWorktreeInclude = usage.usesWorktreeInclude;
      } catch (error) {
        log.warn("Failed to read worktree file usage for analytics", {
          error,
        });
      }
    }

    track(ANALYTICS_EVENTS.TASK_CREATED, {
      auto_run: !!input.executionMode,
      created_from: "command-menu",
      repository_provider: input.repository ? "github" : "none",
      workspace_mode: workspaceMode,
      has_branch: !!input.branch,
      has_environment_setup:
        workspaceMode === "worktree" ? !!input.environmentId : undefined,
      has_sandbox_environment:
        workspaceMode === "cloud" ? !!input.sandboxEnvironmentId : undefined,
      cloud_run_source:
        workspaceMode === "cloud"
          ? (input.cloudRunSource ?? "manual")
          : undefined,
      cloud_pr_authorship_mode:
        workspaceMode === "cloud" ? input.cloudPrAuthorshipMode : undefined,
      signal_report_id: input.signalReportId,
      uses_worktree_link: usesWorktreeLink,
      uses_worktree_include: usesWorktreeInclude,
      adapter: input.adapter,
    });
  } catch (error) {
    log.warn("Failed to track Task created event", { error });
  }
}

export function useTaskCreation({
  editorRef,
  sessionId,
  selectedDirectory,
  selectedRepository,
  repositories,
  githubIntegrationId,
  githubUserIntegrationId,
  workspaceMode,
  branch,
  editorIsEmpty,
  executionMode,
  adapter,
  runtime = "acp",
  model,
  reasoningLevel,
  contextWindow,
  fastMode,
  environmentId,
  sandboxEnvironmentId,
  customImageId,
  signalReportId,
  channelContext,
  channelContextPath,
  submissionBlocked = false,
  channelName,
  channelId,
  channelContextId,
  allowNoRepo,
  onTaskCreated,
  onTaskCreatedEffect,
}: UseTaskCreationOptions): UseTaskCreationReturn {
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [isExitingComposer, setIsExitingComposer] = useState(false);
  const hostClient = useHostTRPCClient();
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const defaultAdditionalDirectoriesQuery = useQuery(
    trpc.additionalDirectories.listDefaults.queryOptions(),
  );
  const defaultAdditionalDirectories =
    defaultAdditionalDirectoriesQuery.data ?? [];
  const [additionalDirectoriesOverride, setAdditionalDirectoriesOverride] =
    useState<string[] | null>(null);
  const additionalDirectories =
    additionalDirectoriesOverride ?? defaultAdditionalDirectories;
  // Importable local MCP servers for cloud runs, self-fetched like the
  // additional-directory defaults above rather than threaded in by callers.
  const { servers: localMcpServers, isLoading: localMcpServersLoading } =
    useLocalMcpCloudServers(workspaceMode === "cloud");
  const taskService = useService<TaskService>(TASK_SERVICE);
  const clearTaskInputReportAssociation = useTaskInputPrefillStore(
    (s) => s.clearReportAssociation,
  );
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const { invalidateTasks } = useCreateTask();
  const { isOnline } = useConnectivity();
  // Used to name the task occupying a branch's worktree when reuse is blocked.
  const { data: tasks } = useTasks();

  // Tasks created without a channel default into the user's private #me channel so they
  // surface in the Channels space instead of staying unfiled. #me is per-user, so this
  // cannot collide across teammates; before the list loads the task is created unfiled.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const { personalChannel } = useTaskChannels({ enabled: bluebirdEnabled });

  const hasRequiredPath = allowNoRepo
    ? true
    : workspaceMode === "cloud"
      ? !!selectedRepository
      : !!selectedDirectory;
  const canSubmitBase =
    isAuthenticated &&
    isOnline &&
    hasRequiredPath &&
    !isCreatingTask &&
    !submissionBlocked;
  const canSubmit = !!editorRef.current && canSubmitBase && !editorIsEmpty;

  const handleSubmit = useCallback(
    async (contentOverride?: EditorContent): Promise<boolean> => {
      const editor = editorRef.current;
      if (!editor) return false;
      const allowSubmit = contentOverride ? canSubmitBase : canSubmit;
      if (!allowSubmit) return false;

      // Capture everything owned by the mounted composer before the first
      // await. Switching tabs unmounts it, but task creation must continue with
      // the exact prompt and tab that the user submitted.
      const originTabId = getCurrentBrowserTabId();
      const content = contentOverride ?? editor.getContent();
      const plainPromptText = contentToPlainText(content).trim();
      const serializedContent = contentToXml(content).trim();
      const filePaths = extractFilePaths(content);

      // Held for the whole submit, pre-flight awaits included, so a second
      // Enter lands after `canSubmitBase` has already gone false.
      setIsCreatingTask(true);

      try {
        // Block over-limit cloud creation before the pending view so it doesn't flash.
        if (workspaceMode === "cloud" && !(await assertCloudUsageAvailable())) {
          return false;
        }

        // The local MCP server classification is fetched lazily on entering cloud
        // mode; submitting before it resolves would silently drop importedMcpServers/
        // relayedMcpServers below instead of including the user's local servers.
        if (workspaceMode === "cloud" && localMcpServersLoading) {
          toast.error("Still checking your local MCP servers", {
            description: "Try again in a moment.",
          });
          return false;
        }

        // Confirm a couple of worktree branch situations before starting the
        // task. Done before the pending view so a dialog (and a cancel) don't
        // leave a half-started task on screen. Reusing an existing worktree takes
        // priority over checking out a remote branch.
        let allowRemoteBranchCheckout = false;
        let reuseExistingWorktree = false;
        if (workspaceMode === "worktree" && branch && selectedDirectory) {
          try {
            const { status, existingWorktreePath, existingWorktreeTaskId } =
              await hostClient.workspace.checkWorktreeBranch.query({
                mainRepoPath: selectedDirectory,
                branch,
              });
            if (existingWorktreeTaskId) {
              // The branch's worktree already belongs to another task. Don't
              // create a duplicate; point the user at the task using it.
              const occupant = tasks?.find(
                (t) => t.id === existingWorktreeTaskId,
              );
              toast.error("Worktree already in use", {
                description: occupant
                  ? `${branch} already has a worktree used by "${occupant.title}". Open that task to keep working there.`
                  : `${branch} already has a worktree used by another task.`,
              });
              return false;
            }
            if (existingWorktreePath) {
              const confirmed = await useExistingWorktreeConfirmStore
                .getState()
                .confirm(branch, existingWorktreePath);
              if (!confirmed) {
                return false;
              }
              reuseExistingWorktree = true;
            } else if (status === "remote-only") {
              const confirmed = await useRemoteBranchConfirmStore
                .getState()
                .confirm(branch);
              if (!confirmed) {
                return false;
              }
              allowRemoteBranchCheckout = true;
            }
          } catch (error) {
            log.warn("Failed to check worktree branch availability", { error });
          }
        }

        const shouldShowPendingView = !onTaskCreated && !!plainPromptText;
        const pendingTaskKey = shouldShowPendingView
          ? generatePendingTaskKey()
          : null;

        if (pendingTaskKey) {
          pendingTaskPromptStoreApi.set(pendingTaskKey, {
            promptText: plainPromptText,
            attachments: (content.attachments ?? []).map((a) => ({
              id: a.id,
              label: a.label,
            })),
          });
          // Fade the composer out before the chat fades in, so the phases
          // hand over instead of cutting.
          setIsExitingComposer(true);
          await waitForComposerExit();
          navigateBrowserTab(
            originTabId,
            {
              href: `/tasks/pending/${pendingTaskKey}`,
              title: "New task",
            },
            () => navigateToTaskPending(pendingTaskKey),
          );
        }

        let createdTaskId: string | undefined;

        try {
          if (!contentOverride) {
            if (plainPromptText) {
              useTaskInputHistoryStore.getState().addPrompt(plainPromptText);
            }
          }

          const settings = useSettingsStore.getState();
          const defaultedChannelId =
            bluebirdEnabled && !channelId && !channelName
              ? personalChannel?.id
              : undefined;

          const localMcpServersForRun = partitionLocalMcpServersForRun(
            localMcpServers,
            adapter,
          );
          const input = prepareTaskInput(serializedContent, filePaths, {
            // Repo-optional surfaces may still supply an explicit task folder or
            // repository selection; otherwise creation falls back to scratch.
            selectedDirectory: selectedDirectory || undefined,
            selectedRepository: allowNoRepo ? null : selectedRepository,
            repositories,
            githubIntegrationId,
            githubUserIntegrationId,
            workspaceMode,
            branch,
            allowRemoteBranchCheckout,
            reuseExistingWorktree,
            executionMode,
            adapter,
            runtime,
            model,
            reasoningLevel,
            contextWindow,
            fastMode,
            environmentId,
            sandboxEnvironmentId,
            customImageId,
            signalReportId,
            additionalDirectories,
            channelContext,
            channelContextPath,
            channelName,
            channelId: channelId ?? defaultedChannelId,
            channelContextId,
            customInstructions: getEffectiveCustomInstructions(settings),
            autoPublishCloudRuns: settings.autoPublishCloudRuns,
            rtkEnabledCloud: settings.rtkEnabledCloud,
            allowNoRepo,
            importedMcpServers: localMcpServersForRun.imported,
            relayedMcpServers: localMcpServersForRun.relayed,
          });

          if (executionMode) {
            useSettingsStore
              .getState()
              .setLastUsedInitialTaskMode(executionMode);
          }

          const result = await taskService.createTask(
            input,
            (output) => {
              invalidateTasks(output.task);
              // Stash the prompt's local attachment paths so the chat-title
              // generator can read their contents when naming the task — needed
              // for pasted-text prompts whose only signal is the file body, and
              // especially for cloud tasks where the local path is otherwise lost
              // once the file is uploaded as an artifact.
              // Exclude folder chips — only file paths are readable by the title
              // generator's readAbsoluteFile call.
              const folderIds = new Set(
                content.segments.flatMap((seg) =>
                  seg.type === "chip" && seg.chip.type === "folder"
                    ? [seg.chip.id]
                    : [],
                ),
              );
              const fileOnlyPaths = filePaths.filter((p) => !folderIds.has(p));
              if (fileOnlyPaths.length > 0) {
                titleAttachmentStoreApi.set(output.task.id, fileOnlyPaths);
              }
              if (signalReportId) {
                clearTaskInputReportAssociation();
              }
              createdTaskId = output.task.id;
              if (pendingTaskKey) {
                pendingTaskPromptStoreApi.move(pendingTaskKey, output.task.id);
              }
              // Clear only the editor that submitted. The same component can
              // render another browser tab before this callback runs; clearing
              // it would erase that tab's draft. The origin's persisted draft
              // is cleared by session id after task creation succeeds.
              if (
                !pendingTaskKey &&
                !contentOverride &&
                editorRef.current === editor &&
                getCurrentBrowserTabId() === originTabId
              ) {
                editor.clear();
              }
              if (defaultedChannelId) {
                track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                  action_type: "file_task",
                  surface: "task_input",
                  channel_id: defaultedChannelId,
                  task_id: output.task.id,
                  success: true,
                });
              }
              onTaskCreatedEffect?.(output.task);
              if (onTaskCreated) {
                onTaskCreated(output.task);
              } else {
                void openTask(output.task, {
                  channelId,
                  tabId: originTabId,
                });
              }
              useTourStore.getState().completeTour(createFirstTaskTour.id);
              // Pre-flight already ran above for cloud; skip the service's duplicate check.
            },
            { skipCloudUsagePreflight: true },
          );

          if (result.success && result.data.provisioningError) {
            // Worktree provisioning failed but the task (and its prompt) was kept
            // so the user can retry setup on it. Stay on the task the onTaskReady
            // callback already navigated to — don't reopen the composer — and
            // flag the failure so the task view shows a retry prompt.
            useProvisioningStore
              .getState()
              .setFailed(result.data.task.id, result.data.provisioningError);
            toastError(
              getErrorTitle("workspace_creation"),
              result.data.provisioningError,
            );
          }

          if (result.success) {
            if (!result.data.provisioningError) {
              if (pendingTaskKey) {
                pendingTaskPromptStoreApi.clear(pendingTaskKey);
              }
              if (createdTaskId) {
                pendingTaskPromptStoreApi.clear(createdTaskId);
              }
            }
            setAdditionalDirectoriesOverride(null);
            // Guarantee the editor draft is wiped on success. editor.clear()
            // above only runs inside the onTaskReady callback (and after it
            // navigates the editor may be torn down); clearing the persisted
            // draft directly here always runs and survives the unmount, so a
            // submitted prompt never reappears on the next new task.
            if (!contentOverride) {
              useDraftStore.getState().actions.setDraft(sessionId, null);
            }
            // The task-level repository/folder pick is consumed by this task;
            // the next one starts from the space defaults again ("save to
            // space" is the durable path).
            if (allowNoRepo && channelId) {
              useTaskRepositoryDraftStore.getState().clearDraft(channelId);
            }
            void trackTaskCreated(input, selectedDirectory, hostClient);
            // Repo-less channel tasks create no workspace row (the agent runs in
            // a scratch dir surfaced as a synthetic workspace), so the normal
            // workspace.create invalidation never fires. Refresh the workspace
            // cache so the task view resolves its cwd and skips the repo prompt.
            if (allowNoRepo) {
              void queryClient.invalidateQueries({
                queryKey: trpc.workspace.getAll.queryKey(),
              });
            }
          }

          if (!result.success) {
            track(ANALYTICS_EVENTS.TASK_CREATION_FAILED, {
              error_type: "task_creation_failed",
              failed_step: result.failedStep,
            });
            // Usage-limit blocks already show the upgrade modal; don't also toast an error.
            if (isUsageLimitResult(result)) {
              useUsageLimitStore.getState().show({ cause: "org_limit" });
              log.warn("Cloud task creation blocked by usage limit");
            } else {
              const title = getErrorTitle(result.failedStep);
              toastError(title, result.error);
              log.error("Task creation failed", {
                failedStep: result.failedStep,
                error: result.error,
              });
            }
            if (pendingTaskKey) {
              pendingTaskPromptStoreApi.clear(pendingTaskKey);
              if (createdTaskId) {
                pendingTaskPromptStoreApi.clear(createdTaskId);
              }
              restoreTaskInputTab(originTabId, channelContextId ?? channelId);
            }
          }
          return result.success;
        } catch (error) {
          track(ANALYTICS_EVENTS.TASK_CREATION_FAILED, {
            error_type: "unexpected_error",
          });
          toastError("Failed to create task", error);
          log.error("Unexpected error during task creation", { error });
          if (pendingTaskKey) {
            pendingTaskPromptStoreApi.clear(pendingTaskKey);
            if (createdTaskId) {
              pendingTaskPromptStoreApi.clear(createdTaskId);
            }
            restoreTaskInputTab(originTabId, channelContextId ?? channelId);
          }
          return false;
        }
      } finally {
        setIsCreatingTask(false);
        setIsExitingComposer(false);
      }
    },
    [
      canSubmit,
      canSubmitBase,
      editorRef,
      sessionId,
      selectedDirectory,
      selectedRepository,
      repositories,
      githubIntegrationId,
      githubUserIntegrationId,
      workspaceMode,
      branch,
      executionMode,
      adapter,
      runtime,
      model,
      reasoningLevel,
      contextWindow,
      fastMode,
      environmentId,
      sandboxEnvironmentId,
      customImageId,
      signalReportId,
      additionalDirectories,
      channelContext,
      channelContextPath,
      channelName,
      channelId,
      channelContextId,
      allowNoRepo,
      bluebirdEnabled,
      personalChannel?.id,
      localMcpServers,
      localMcpServersLoading,
      clearTaskInputReportAssociation,
      invalidateTasks,
      onTaskCreated,
      onTaskCreatedEffect,
      hostClient,
      trpc,
      queryClient,
      taskService,
      tasks,
    ],
  );

  return {
    isCreatingTask,
    isExitingComposer,
    canSubmit,
    handleSubmit,
    additionalDirectories,
    setAdditionalDirectories: setAdditionalDirectoriesOverride,
  };
}
