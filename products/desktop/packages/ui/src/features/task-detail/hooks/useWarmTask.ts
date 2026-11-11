import {
  WARM_TASK_SERVICE,
  type WarmTaskDraft,
  type WarmTaskOptions,
  type WarmTaskService,
} from "@posthog/core/task-detail/warmTaskService";
import { useService } from "@posthog/di/react";
import {
  type AgentRuntime,
  type ExecutionMode,
  TASKS_PREWARM_SANDBOX_FLAG,
  type WorkspaceMode,
} from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useEffect, useMemo } from "react";
import { getAuthIdentity, useAuthStateValue } from "../../auth/store";
import { useCurrentUser } from "../../auth/useCurrentUser";
export interface UseWarmTaskOptions {
  sessionId: string;
  workspaceMode: WorkspaceMode;
  claudeModelAccess?: string;
  codexModelAccess?: string;
  selectedRepository?: string | null;
  repositories?: string[];
  githubIntegrationId?: number;
  allowNoRepo?: boolean;
  branch?: string | null;
  editorIsEmpty: boolean;
  agentRuntime?: AgentRuntime;
  runtimeAdapter?: string | null;
  model?: string | null;
  reasoningEffort?: string | null;
  permissionMode?: ExecutionMode | null;
  contextWindow?: "200k" | "1m";
  fastMode?: boolean;
  sandboxEnvironmentId?: string | null;
  customImageId?: string | null;
}

export function useWarmTask({
  sessionId,
  workspaceMode,
  claudeModelAccess,
  codexModelAccess,
  selectedRepository,
  repositories,
  githubIntegrationId,
  allowNoRepo = false,
  branch,
  editorIsEmpty,
  agentRuntime,
  runtimeAdapter,
  model,
  reasoningEffort,
  permissionMode,
  contextWindow,
  fastMode,
  sandboxEnvironmentId,
  customImageId,
}: UseWarmTaskOptions): WarmTaskDraft | null {
  const enabled = useFeatureFlag(TASKS_PREWARM_SANDBOX_FLAG);
  const client = useOptionalAuthenticatedClient();

  const service = useService<WarmTaskService>(WARM_TASK_SERVICE);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const { data: user } = useCurrentUser({ client });
  const scope =
    user?.uuid && authIdentity
      ? JSON.stringify([authIdentity, user.uuid])
      : null;
  const draft = useMemo(
    () => (scope ? service.draft(scope, sessionId) : null),
    [service, scope, sessionId],
  );
  useEffect(() => draft?.attach(), [draft]);

  const isCloud = workspaceMode === "cloud";
  const normalizedBranch = branch ?? null;
  const normalizedRuntimeAdapter = runtimeAdapter ?? null;
  const normalizedModel = model ?? null;
  const normalizedReasoningEffort = reasoningEffort ?? null;
  const normalizedPermissionMode = runtimeAdapter
    ? (permissionMode ?? null)
    : null;
  const normalizedSandboxEnvironmentId = sandboxEnvironmentId ?? null;
  const normalizedCustomImageId = customImageId ?? null;
  // Repo-less channel tasks deliberately discard any persisted/stale picker
  // selection on submit, so warming and lease matching must do the same.
  const warmRepositories = useMemo(
    () =>
      allowNoRepo
        ? (repositories ?? [])
        : selectedRepository
          ? [selectedRepository]
          : [],
    [allowNoRepo, repositories, selectedRepository],
  );
  const warmRepository = warmRepositories[0] ?? null;
  const warmGithubIntegrationId = warmRepositories.length
    ? (githubIntegrationId ?? null)
    : null;
  const heldLeaseIsUnusable =
    agentRuntime === "pi" ||
    contextWindow === "1m" ||
    fastMode === true ||
    claudeModelAccess === "own-subscription" ||
    codexModelAccess === "own-subscription";
  const eligible =
    enabled &&
    !heldLeaseIsUnusable &&
    isCloud &&
    !!client &&
    (allowNoRepo || (!!warmRepository && warmGithubIntegrationId !== null)) &&
    (!warmRepositories.length || warmGithubIntegrationId !== null) &&
    !editorIsEmpty;
  const options = useMemo<WarmTaskOptions>(
    () => ({
      repository: warmRepository,
      ...(repositories !== undefined ? { repositories: warmRepositories } : {}),
      github_integration: warmGithubIntegrationId,
      branch: normalizedBranch,
      runtime_adapter: normalizedRuntimeAdapter,
      model: normalizedModel,
      reasoning_effort: normalizedReasoningEffort,
      initial_permission_mode: normalizedPermissionMode,
      ...(normalizedSandboxEnvironmentId
        ? { sandbox_environment_id: normalizedSandboxEnvironmentId }
        : {}),
      ...(normalizedCustomImageId
        ? { custom_image_id: normalizedCustomImageId }
        : {}),
    }),
    [
      warmRepository,
      repositories,
      warmRepositories,
      warmGithubIntegrationId,
      normalizedBranch,
      normalizedRuntimeAdapter,
      normalizedModel,
      normalizedReasoningEffort,
      normalizedPermissionMode,
      normalizedSandboxEnvironmentId,
      normalizedCustomImageId,
    ],
  );
  useEffect(() => {
    draft?.update(eligible ? options : null, client);
  }, [draft, eligible, options, client]);
  return draft;
}
