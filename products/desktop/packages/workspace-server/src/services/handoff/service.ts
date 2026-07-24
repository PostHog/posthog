import { POSTHOG_NOTIFICATIONS } from "@posthog/agent";
import { HandoffCheckpointTracker } from "@posthog/agent/handoff-checkpoint";
import { PostHogAPIClient } from "@posthog/agent/posthog-api";
import type * as AgentResume from "@posthog/agent/resume";
import {
  formatConversationForResume,
  resumeFromLog,
} from "@posthog/agent/resume";
import type { GitHandoffBranchDivergence } from "@posthog/git/handoff";
import {
  APP_LIFECYCLE_SERVICE,
  type IAppLifecycle,
} from "@posthog/platform/app-lifecycle";
import { DIALOG_SERVICE, type IDialog } from "@posthog/platform/dialog";
import type {
  GitHandoffCheckpoint,
  HandoffApiContext,
  HandoffChangedFile,
  HandoffHost,
  HandoffLocalGitState,
  HandoffReconnectParams,
  HandoffResumeStateResult,
  WorkspaceMode,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  REPOSITORY_REPOSITORY,
  WORKSPACE_REPOSITORY,
} from "../../db/identifiers";
import type { IRepositoryRepository } from "../../db/repositories/repository-repository";
import type { IWorkspaceRepository } from "../../db/repositories/workspace-repository";
import type { AgentService } from "../agent/agent";
import type { AgentAuthAdapter } from "../agent/auth-adapter";
import { AGENT_AUTH_ADAPTER, AGENT_SERVICE } from "../agent/identifiers";
import { HANDOFF_GIT_GATEWAY, HANDOFF_LOG_GATEWAY } from "./identifiers";
import type { HandoffGitGateway, HandoffLogGateway } from "./ports";

const CONTINUE_DIVERGENCE_BUTTON = 1;

/**
 * Host implementation of the core handoff orchestration's HANDOFF_HOST port.
 * Owns the agent runtime glue (api client, checkpoint tracker, log resume),
 * workspace/repository persistence, and the diverged-branch confirmation. Git
 * and local-log syscalls run in the workspace-server child process, reached
 * through the injected gateways.
 */
@injectable()
export class HandoffHostService implements HandoffHost {
  constructor(
    @inject(AGENT_SERVICE)
    private readonly agentService: AgentService,
    @inject(AGENT_AUTH_ADAPTER)
    private readonly agentAuthAdapter: AgentAuthAdapter,
    @inject(WORKSPACE_REPOSITORY)
    private readonly workspaceRepo: IWorkspaceRepository,
    @inject(REPOSITORY_REPOSITORY)
    private readonly repositoryRepo: IRepositoryRepository,
    @inject(DIALOG_SERVICE)
    private readonly dialog: IDialog,
    @inject(APP_LIFECYCLE_SERVICE)
    private readonly appLifecycle: IAppLifecycle,
    @inject(HANDOFF_GIT_GATEWAY)
    private readonly git: HandoffGitGateway,
    @inject(HANDOFF_LOG_GATEWAY)
    private readonly logs: HandoffLogGateway,
  ) {}

  getChangedFiles(repoPath: string): Promise<readonly HandoffChangedFile[]> {
    return this.git.getChangedFiles(repoPath);
  }

  getLocalGitState(repoPath: string): Promise<HandoffLocalGitState> {
    return this.git.getLocalGitState(repoPath);
  }

  async markRunEnvironmentLocal(
    ctx: HandoffApiContext,
    taskId: string,
    runId: string,
  ): Promise<void> {
    const apiClient = this.createApiClient(ctx);
    await apiClient.updateTaskRun(taskId, runId, { environment: "local" });
  }

  async fetchResumeState(
    ctx: HandoffApiContext,
    taskId: string,
    runId: string,
  ): Promise<HandoffResumeStateResult> {
    const apiClient = this.createApiClient(ctx);
    const taskRun = await apiClient.getTaskRun(taskId, runId);
    const resumeState = await resumeFromLog({ taskId, runId, apiClient });
    return {
      resumeState: {
        conversation: resumeState.conversation,
        latestGitCheckpoint: resumeState.latestGitCheckpoint,
      },
      cloudLogUrl: taskRun.log_url ?? null,
    };
  }

  formatConversation(conversation: unknown[]): string {
    return formatConversationForResume(
      conversation as AgentResume.ConversationTurn[],
    );
  }

  async applyGitCheckpoint(
    ctx: HandoffApiContext,
    checkpoint: GitHandoffCheckpoint,
    repoPath: string,
    taskId: string,
    runId: string,
    localGitState?: HandoffLocalGitState,
  ): Promise<void> {
    const apiClient = this.createApiClient(ctx);
    const tracker = new HandoffCheckpointTracker({
      repositoryPath: repoPath,
      taskId,
      runId,
      apiClient,
    });
    await tracker.applyFromHandoff(checkpoint, {
      localGitState,
      onDivergedBranch: (divergence) =>
        this.confirmDivergedBranchReset(divergence),
    });
  }

  reconnectSession(
    params: HandoffReconnectParams,
  ): Promise<{ sessionId: string } | null> {
    return this.agentService.reconnectSession(params);
  }

  attachWorkspaceToFolder(
    taskId: string,
    repoPath: string,
  ): { revert: () => void } {
    const repository = this.repositoryRepo.findByPath(repoPath);
    if (!repository) {
      throw new Error(
        `No registered folder for path '${repoPath}' — cannot attach workspace`,
      );
    }
    const previous = this.workspaceRepo.findByTaskId(taskId);
    if (!previous) {
      throw new Error(`No workspace exists for task ${taskId}`);
    }
    if (previous.mode === "local" && previous.repositoryId === repository.id) {
      return { revert: () => {} };
    }
    this.workspaceRepo.setModeAndRepository(taskId, "local", repository.id);
    return {
      revert: () => {
        this.workspaceRepo.setModeAndRepository(
          taskId,
          previous.mode,
          previous.repositoryId,
        );
      },
    };
  }

  async seedLocalLogs(runId: string, logUrl: string): Promise<void> {
    const response = await fetch(logUrl);
    if (!response.ok) return;
    const content = await response.text();
    if (!content?.trim()) return;
    await this.logs.seedLocalLogs(runId, content);
  }

  setPendingContext(taskRunId: string, context: string): void {
    this.agentService.setPendingContext(taskRunId, context);
  }

  async killSession(taskRunId: string): Promise<void> {
    await this.agentService.cancelSession(taskRunId);
  }

  updateWorkspaceMode(taskId: string, mode: WorkspaceMode): void {
    this.workspaceRepo.updateMode(taskId, mode);
  }

  async captureGitCheckpoint(
    ctx: HandoffApiContext,
    repoPath: string,
    taskId: string,
    runId: string,
    localGitState?: HandoffLocalGitState,
  ): Promise<GitHandoffCheckpoint | null> {
    const apiClient = this.createApiClient(ctx);
    const tracker = new HandoffCheckpointTracker({
      repositoryPath: repoPath,
      taskId,
      runId,
      apiClient,
    });
    const checkpoint = await tracker.captureForHandoff(localGitState);
    if (!checkpoint) return null;
    const localCheckpoint = {
      ...checkpoint,
      device: { type: "local" as const },
    };
    return localCheckpoint;
  }

  async persistCheckpointToLog(
    ctx: HandoffApiContext,
    taskId: string,
    runId: string,
    checkpoint: GitHandoffCheckpoint,
  ): Promise<void> {
    const apiClient = this.createApiClient(ctx);
    await apiClient.appendTaskRunLog(taskId, runId, [
      {
        type: "notification",
        timestamp: new Date().toISOString(),
        notification: {
          jsonrpc: "2.0",
          method: POSTHOG_NOTIFICATIONS.GIT_CHECKPOINT,
          params: checkpoint as unknown as Record<string, unknown>,
        },
      },
    ]);
  }

  countLocalLogEntries(runId: string): Promise<number> {
    return this.logs.countLocalLogEntries(runId);
  }

  async resumeRunInCloud(
    ctx: HandoffApiContext,
    taskId: string,
    runId: string,
  ): Promise<void> {
    const apiClient = this.createApiClient(ctx);
    await apiClient.resumeRunInCloud(taskId, runId);
  }

  async cleanupLocalAfterCloudHandoff(
    repoPath: string,
    branchName: string | null,
  ): Promise<void> {
    await this.git.cleanupAfterCloudHandoff(repoPath, branchName);
  }

  deleteLocalLogCache(runId: string): Promise<void> {
    return this.logs.deleteLocalLogCache(runId);
  }

  private createApiClient(ctx: HandoffApiContext): PostHogAPIClient {
    const config = this.agentAuthAdapter.createPosthogConfig({
      apiHost: ctx.apiHost,
      projectId: ctx.teamId,
    });
    return new PostHogAPIClient(config);
  }

  private async confirmDivergedBranchReset(
    divergence: GitHandoffBranchDivergence,
  ): Promise<boolean> {
    await this.appLifecycle.whenReady();

    const response = await this.dialog.confirm({
      severity: "warning",
      options: ["Cancel", "Continue"],
      defaultIndex: 0,
      cancelIndex: 0,
      title: "Local branch has diverged",
      message: `The local branch '${divergence.branch}' has commits that are not in the cloud handoff.`,
      detail:
        `Continuing will reset '${divergence.branch}' from ${divergence.localHead.slice(0, 7)} to ${divergence.cloudHead.slice(0, 7)}.\n\n` +
        "Cancel if you want to keep the current local branch tip.",
    });
    return response === CONTINUE_DIVERGENCE_BUTTON;
  }
}
