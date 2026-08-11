import {
  TASKS_PREWARM_SANDBOX_FLAG,
  type WorkspaceMode,
} from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useEffect, useMemo, useRef } from "react";
import { logger } from "../../../shell/logger";
import { buildWarmTaskLeaseKey, rememberWarmTaskLease } from "./warmTaskLease";

const log = logger.scope("warm-task");

const WARM_DEBOUNCE_MS = 600;

interface UseWarmTaskOptions {
  workspaceMode: WorkspaceMode;
  selectedRepository?: string | null;
  repositories?: string[];
  githubIntegrationId?: number;
  allowNoRepo?: boolean;
  branch?: string | null;
  editorIsEmpty: boolean;
  runtimeAdapter?: string | null;
  model?: string | null;
  reasoningEffort?: string | null;
  sandboxEnvironmentId?: string | null;
  customImageId?: string | null;
}

export function useWarmTask({
  workspaceMode,
  selectedRepository,
  repositories,
  githubIntegrationId,
  allowNoRepo = false,
  branch,
  editorIsEmpty,
  runtimeAdapter,
  model,
  reasoningEffort,
  sandboxEnvironmentId,
  customImageId,
}: UseWarmTaskOptions): void {
  const enabled = useFeatureFlag(TASKS_PREWARM_SANDBOX_FLAG);
  const client = useOptionalAuthenticatedClient();

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastWarmedKeyRef = useRef<string | null>(null);
  const latestKeyRef = useRef<string | null>(null);

  const isCloud = workspaceMode === "cloud";
  const normalizedBranch = branch ?? null;
  const normalizedRuntimeAdapter = runtimeAdapter ?? null;
  const normalizedModel = model ?? null;
  const normalizedReasoningEffort = reasoningEffort ?? null;
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
  const eligible =
    enabled &&
    isCloud &&
    !!client &&
    (allowNoRepo || (!!warmRepository && warmGithubIntegrationId !== null)) &&
    (!warmRepositories.length || warmGithubIntegrationId !== null) &&
    !editorIsEmpty;
  const key =
    allowNoRepo || (warmRepository && warmGithubIntegrationId !== null)
      ? `${warmGithubIntegrationId ?? ""}:${buildWarmTaskLeaseKey({
          repository: warmRepository,
          repositories: warmRepositories,
          branch: normalizedBranch,
          runtimeAdapter: normalizedRuntimeAdapter,
          model: normalizedModel,
          reasoningEffort: normalizedReasoningEffort,
          sandboxEnvironmentId: normalizedSandboxEnvironmentId,
          customImageId: normalizedCustomImageId,
        })}`
      : null;
  useEffect(() => {
    latestKeyRef.current = key;

    const clearDebounce = (): void => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };

    if (!eligible || !key || !client) {
      clearDebounce();
      return;
    }
    if (lastWarmedKeyRef.current === key || debounceRef.current) {
      return;
    }

    const repository = warmRepository;
    const githubIntegration = warmGithubIntegrationId;
    const warmBranch = normalizedBranch;
    const warmRuntimeAdapter = normalizedRuntimeAdapter;
    const warmModel = normalizedModel;
    const warmReasoningEffort = normalizedReasoningEffort;
    const warmSandboxEnvironmentId = normalizedSandboxEnvironmentId;
    const warmCustomImageId = normalizedCustomImageId;
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      lastWarmedKeyRef.current = key;
      void client
        .warmTask({
          repository,
          // Older backends ignore this additive field and fall back to cold creation for multi-repo tasks.
          ...(repositories !== undefined
            ? { repositories: warmRepositories }
            : {}),
          github_integration: githubIntegration,
          branch: warmBranch,
          runtime_adapter: warmRuntimeAdapter,
          model: warmModel,
          reasoning_effort: warmReasoningEffort,
          ...(warmSandboxEnvironmentId
            ? { sandbox_environment_id: warmSandboxEnvironmentId }
            : {}),
          ...(warmCustomImageId ? { custom_image_id: warmCustomImageId } : {}),
        })
        .then((warm) => {
          if (warm && latestKeyRef.current === key) {
            rememberWarmTaskLease(
              buildWarmTaskLeaseKey({
                repository,
                repositories: warmRepositories,
                branch: warmBranch,
                runtimeAdapter: warmRuntimeAdapter,
                model: warmModel,
                reasoningEffort: warmReasoningEffort,
                sandboxEnvironmentId: warmSandboxEnvironmentId,
                customImageId: warmCustomImageId,
              }),
              { taskId: warm.task_id, runId: warm.run_id },
            );
          }
        })
        .catch((error) => {
          if (latestKeyRef.current === key) {
            lastWarmedKeyRef.current = null;
          }
          log.warn("Failed to warm task", { error });
        });
    }, WARM_DEBOUNCE_MS);

    return clearDebounce;
  }, [
    eligible,
    key,
    client,
    warmRepository,
    warmRepositories,
    repositories,
    warmGithubIntegrationId,
    normalizedBranch,
    normalizedRuntimeAdapter,
    normalizedModel,
    normalizedReasoningEffort,
    normalizedSandboxEnvironmentId,
    normalizedCustomImageId,
  ]);
}
