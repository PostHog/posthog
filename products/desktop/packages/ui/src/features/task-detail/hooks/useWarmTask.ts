import {
  TASKS_PREWARM_SANDBOX_FLAG,
  type WorkspaceMode,
} from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useEffect, useRef } from "react";
import { logger } from "../../../shell/logger";
import { buildWarmTaskLeaseKey, rememberWarmTaskLease } from "./warmTaskLease";

const log = logger.scope("warm-task");

const WARM_DEBOUNCE_MS = 600;

interface UseWarmTaskOptions {
  workspaceMode: WorkspaceMode;
  selectedRepository?: string | null;
  githubIntegrationId?: number;
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
  githubIntegrationId,
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
  const eligible =
    enabled &&
    isCloud &&
    !!client &&
    !!selectedRepository &&
    githubIntegrationId !== undefined &&
    !editorIsEmpty;
  const key =
    selectedRepository && githubIntegrationId !== undefined
      ? `${githubIntegrationId}:${buildWarmTaskLeaseKey({
          repository: selectedRepository,
          branch: normalizedBranch,
          runtimeAdapter: normalizedRuntimeAdapter,
          model: normalizedModel,
          reasoningEffort: normalizedReasoningEffort,
          sandboxEnvironmentId: normalizedSandboxEnvironmentId,
          customImageId: normalizedCustomImageId,
        })}`
      : null;
  latestKeyRef.current = key;

  useEffect(() => {
    const clearDebounce = (): void => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };

    if (!eligible || !key || !selectedRepository || !client) {
      clearDebounce();
      return;
    }
    if (lastWarmedKeyRef.current === key || debounceRef.current) {
      return;
    }

    const repository = selectedRepository;
    const githubIntegration = githubIntegrationId as number;
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
    selectedRepository,
    githubIntegrationId,
    normalizedBranch,
    normalizedRuntimeAdapter,
    normalizedModel,
    normalizedReasoningEffort,
    normalizedSandboxEnvironmentId,
    normalizedCustomImageId,
  ]);
}
