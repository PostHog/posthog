import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type {
  DiscoveryFailureReason,
  DiscoverySignalSource,
  ISetupRunService,
} from "@posthog/core/setup/identifiers";
import type { StaleFlagPayload } from "@posthog/core/setup/suggestions";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import {
  EXPERIMENT_SUGGESTIONS_FLAG,
  getCloudUrlFromRegion,
} from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  isTerminalStatus,
  type TaskRunStatus,
} from "@posthog/shared/domain-types";
import { injectable } from "inversify";
import { captureException, track } from "../../shell/analytics";
import { createAuthenticatedClient } from "../auth/authClientImperative";
import { fetchAuthState } from "../auth/authQueries";
import { FEATURE_FLAGS, type FeatureFlags } from "../feature-flags/identifiers";

/**
 * Renderer adapter for the setup discovery/enrichment orchestration. Wraps the
 * host tRPC client (agent/enrichment), the authenticated PostHog API client
 * (task runs), analytics, and build/env flags. Holds the authenticated client
 * created at getDiscoveryContext() time for the duration of the (one-at-a-time)
 * run. Stays host-agnostic: no electron, no @renderer, host capabilities flow
 * through resolveService.
 */
@injectable()
export class SetupRunServiceImpl implements ISetupRunService {
  private client: PostHogAPIClient | null = null;

  private hostClient(): HostTrpcClient {
    return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
  }

  async getDiscoveryContext(): Promise<{
    apiHost: string | null;
    projectId: number | null;
    authed: boolean;
  }> {
    const authState = await fetchAuthState();
    const apiHost = authState.cloudRegion
      ? getCloudUrlFromRegion(authState.cloudRegion)
      : null;
    this.client = createAuthenticatedClient(authState);
    return {
      apiHost,
      projectId: authState.currentProjectId,
      authed: this.client !== null,
    };
  }

  private requireClient(): PostHogAPIClient {
    if (!this.client) {
      throw new Error("Setup discovery: no authenticated client");
    }
    return this.client;
  }

  async createDiscoveryTask(input: {
    title: string;
    description: string;
    jsonSchema: Record<string, unknown>;
  }): Promise<{ id: string }> {
    const task = await this.requireClient().createTask({
      title: input.title,
      description: input.description,
      json_schema: input.jsonSchema,
    });
    return { id: (task as { id: string }).id };
  }

  async createTaskRun(taskId: string): Promise<{ id: string | null }> {
    const run = await this.requireClient().createTaskRun(taskId);
    return { id: run?.id ?? null };
  }

  async getTaskRun(
    taskId: string,
    taskRunId: string,
  ): Promise<{ status: string; tasks: DiscoveredTask[] | null }> {
    const run = await this.requireClient().getTaskRun(taskId, taskRunId);
    const output = run.output as { tasks?: DiscoveredTask[] } | null;
    return { status: run.status, tasks: output?.tasks ?? null };
  }

  isTerminalStatus(status: string): boolean {
    return isTerminalStatus(status as TaskRunStatus);
  }

  async startAgent(input: {
    taskId: string;
    taskRunId: string;
    repoPath: string;
    apiHost: string;
    projectId: number;
    jsonSchema: Record<string, unknown>;
  }): Promise<void> {
    await this.hostClient().agent.start.mutate({
      taskId: input.taskId,
      taskRunId: input.taskRunId,
      repoPath: input.repoPath,
      apiHost: input.apiHost,
      projectId: input.projectId,
      permissionMode: "bypassPermissions",
      jsonSchema: input.jsonSchema,
    });
  }

  async sendPrompt(input: {
    sessionId: string;
    promptText: string;
  }): Promise<void> {
    await this.hostClient().agent.prompt.mutate({
      sessionId: input.sessionId,
      prompt: [{ type: "text", text: input.promptText }],
    });
  }

  subscribeSessionEvents(
    input: { taskRunId: string },
    handlers: {
      onData: (payload: unknown) => void;
      onError: (err: unknown) => void;
    },
  ): { unsubscribe: () => void } {
    return this.hostClient().agent.onSessionEvent.subscribe(
      { taskRunId: input.taskRunId },
      { onData: handlers.onData, onError: handlers.onError },
    );
  }

  async detectPosthogInstallState(
    repoPath: string,
  ): Promise<"initialized" | "not_installed" | "installed_no_init"> {
    return this.hostClient().enrichment.detectPosthogInstallState.query({
      repoPath,
    });
  }

  async findStaleFlagSuggestions(
    repoPath: string,
  ): Promise<StaleFlagPayload[]> {
    return this.hostClient().enrichment.findStaleFlagSuggestions.query({
      repoPath,
    });
  }

  includeExperiments(): boolean {
    return (
      resolveService<FeatureFlags>(FEATURE_FLAGS).isEnabled(
        EXPERIMENT_SUGGESTIONS_FLAG,
      ) || import.meta.env.DEV
    );
  }

  trackDiscoveryStarted(p: { taskId: string; taskRunId: string }): void {
    track(ANALYTICS_EVENTS.SETUP_DISCOVERY_STARTED, {
      discovery_task_id: p.taskId,
      discovery_task_run_id: p.taskRunId,
    });
  }

  trackDiscoveryCompleted(p: {
    taskId: string;
    taskRunId: string;
    taskCount: number;
    durationSeconds: number;
    signalSource: DiscoverySignalSource;
  }): void {
    track(ANALYTICS_EVENTS.SETUP_DISCOVERY_COMPLETED, {
      discovery_task_id: p.taskId,
      discovery_task_run_id: p.taskRunId,
      task_count: p.taskCount,
      duration_seconds: p.durationSeconds,
      signal_source: p.signalSource,
    });
  }

  trackDiscoveryFailed(p: {
    taskId?: string;
    taskRunId?: string;
    reason: DiscoveryFailureReason;
    errorMessage?: string;
  }): void {
    track(ANALYTICS_EVENTS.SETUP_DISCOVERY_FAILED, {
      discovery_task_id: p.taskId,
      discovery_task_run_id: p.taskRunId,
      reason: p.reason,
      error_message: p.errorMessage,
    });
  }

  reportError(error: Error, scope: string): void {
    captureException(error, { scope });
  }
}
