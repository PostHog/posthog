import type { ContentBlock } from "@agentclientprotocol/sdk";
import { CLOUD_USAGE_LIMIT_ERROR_MESSAGE } from "@posthog/api-client/posthog-client";
import {
  CLOUD_ARTIFACT_SERVICE,
  type CloudArtifactClient,
} from "@posthog/core/sessions/cloudArtifactIdentifiers";
import type { CloudArtifactService } from "@posthog/core/sessions/cloudArtifactService";
import { getCloudPromptTransport } from "@posthog/core/sessions/cloudPrompt";
import type { TaskCreationApiClient } from "@posthog/core/task-detail/taskCreationApiClient";
import type {
  CloudPromptTransport,
  CreatedWorkspaceInfo,
  CreateWorkspaceArgs,
  DetectedRepo,
  ImportedClaudeCliSession,
  ITaskCreationHost,
  RecordClaudeCliImportArgs,
  SetupActionDispatch,
  TaskEnvironment,
  TaskFolderInfo,
} from "@posthog/core/task-detail/taskCreationHost";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { expandTildePath, type Workspace } from "@posthog/shared";
import { injectable } from "inversify";
import { track } from "../../shell/analytics";
import { getAuthenticatedClient } from "../auth/authClientImperative";
import { assertCloudUsageAvailable } from "../billing/preflightCloudUsage";
import { resolveLocalSkillPrompt } from "../message-editor/commands";
import { DEFAULT_PANEL_IDS } from "../panels/panelConstants";
import { usePanelLayoutStore } from "../panels/panelLayoutStore";
import { useProvisioningStore } from "../provisioning/store";
import { takeWarmTaskLease } from "./hooks/warmTaskLease";

interface EnvironmentHostClient {
  environment: {
    get: {
      query(args: {
        repoPath: string;
        id: string;
      }): Promise<TaskEnvironment | null>;
    };
  };
}

function hostClient(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

@injectable()
export class TrpcTaskCreationHost implements ITaskCreationHost {
  getAuthenticatedClient(): Promise<TaskCreationApiClient | null> {
    return getAuthenticatedClient() as Promise<TaskCreationApiClient | null>;
  }

  async assertCloudUsageAvailable(): Promise<void> {
    if (!(await assertCloudUsageAvailable())) {
      throw new Error(CLOUD_USAGE_LIMIT_ERROR_MESSAGE);
    }
  }

  async getTaskDirectory(
    taskId: string,
    repoKey?: string,
  ): Promise<string | null> {
    const workspace = await this.getWorkspace(taskId);
    if (workspace?.folderPath) {
      return expandTildePath(workspace.folderPath);
    }

    if (repoKey) {
      const repo = await hostClient().folders.getRepositoryByRemoteUrl.query({
        remoteUrl: repoKey,
      });
      if (repo) {
        return expandTildePath(repo.path);
      }
    }

    return null;
  }

  async ensureScratchDir(taskId: string): Promise<string> {
    const { path } = await hostClient().workspace.ensureScratchDir.mutate({
      taskId,
    });
    return path;
  }

  async getWorkspace(taskId: string): Promise<Workspace | null> {
    const workspaces = await hostClient().workspace.getAll.query();
    return workspaces?.[taskId] ?? null;
  }

  createWorkspace(args: CreateWorkspaceArgs): Promise<CreatedWorkspaceInfo> {
    return hostClient().workspace.create.mutate(args);
  }

  async deleteWorkspace(args: {
    taskId: string;
    mainRepoPath: string;
  }): Promise<void> {
    await hostClient().workspace.delete.mutate(args);
  }

  getFolders(): Promise<TaskFolderInfo[]> {
    return hostClient().folders.getFolders.query();
  }

  addFolder(args: { folderPath: string }): Promise<TaskFolderInfo> {
    return hostClient().folders.addFolder.mutate(args);
  }

  async addAdditionalDirectory(args: {
    taskId: string;
    path: string;
  }): Promise<void> {
    await hostClient().additionalDirectories.addForTask.mutate(args);
  }

  async removeAdditionalDirectory(args: {
    taskId: string;
    path: string;
  }): Promise<void> {
    await hostClient().additionalDirectories.removeForTask.mutate(args);
  }

  getEnvironment(args: {
    repoPath: string;
    id: string;
  }): Promise<TaskEnvironment | null> {
    return (
      hostClient() as unknown as EnvironmentHostClient
    ).environment.get.query(args);
  }

  detectRepo(args: { directoryPath: string }): Promise<DetectedRepo | null> {
    return hostClient().git.detectRepo.query(args);
  }

  getCloudPromptTransport(
    prompt: string | ContentBlock[],
    filePaths?: string[],
  ): CloudPromptTransport {
    return getCloudPromptTransport(prompt, filePaths);
  }

  async resolveLocalSkillCommandPrompt(prompt: string): Promise<string> {
    return (
      (await resolveLocalSkillPrompt(prompt, () =>
        hostClient().skills.list.query(),
      )) ?? prompt
    );
  }

  takeWarmTaskLease(args: {
    repository: string;
    branch?: string | null;
    runtimeAdapter?: string | null;
    model?: string | null;
    reasoningEffort?: string | null;
    sandboxEnvironmentId?: string | null;
    customImageId?: string | null;
  }): { taskId: string; runId: string } | null {
    return takeWarmTaskLease(args);
  }

  uploadRunAttachments(
    client: TaskCreationApiClient,
    taskId: string,
    runId: string,
    filePaths: string[],
    skillBundles?: CloudPromptTransport["skillBundles"],
  ): Promise<string[]> {
    return resolveService<CloudArtifactService>(
      CLOUD_ARTIFACT_SERVICE,
    ).uploadRunAttachments(
      client as unknown as CloudArtifactClient,
      taskId,
      runId,
      filePaths,
      skillBundles,
    );
  }

  setProvisioningActive(taskId: string): void {
    useProvisioningStore.getState().setActive(taskId);
  }

  clearProvisioning(taskId: string): void {
    useProvisioningStore.getState().clear(taskId);
  }

  dispatchSetupAction(args: SetupActionDispatch): void {
    const actionId = `setup-${args.taskId}-${Date.now()}`;
    usePanelLayoutStore
      .getState()
      .addActionTab(args.taskId, DEFAULT_PANEL_IDS.MAIN_PANEL, {
        actionId,
        command: args.command,
        cwd: args.cwd,
        label: args.label,
      });
  }

  track(event: string, props?: Record<string, unknown>): void {
    (track as (event: string, props?: Record<string, unknown>) => void)(
      event,
      props,
    );
  }

  importClaudeCliSession(args: {
    repoPath: string;
    sourceSessionId: string;
  }): Promise<ImportedClaudeCliSession> {
    return hostClient().claudeCliSessions.import.mutate(args);
  }

  async deleteClaudeCliImport(args: {
    repoPath: string;
    importedSessionId: string;
  }): Promise<void> {
    await hostClient().claudeCliSessions.deleteImport.mutate(args);
  }

  async recordClaudeCliImport(args: RecordClaudeCliImportArgs): Promise<void> {
    await hostClient().claudeCliSessions.recordImport.mutate(args);
  }

  async deleteClaudeCliImportRecord(args: {
    importedSessionId: string;
  }): Promise<void> {
    await hostClient().claudeCliSessions.deleteImportRecord.mutate(args);
  }

  async linkTaskBranch(args: {
    taskId: string;
    branchName: string;
  }): Promise<void> {
    await hostClient().workspace.linkBranch.mutate(args);
  }
}
