import type { TaskPreviewPortsHost } from "@posthog/core/task-preview/taskPreviewPorts";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { TASK_PORT_PREVIEW_FLAG } from "@posthog/shared";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import { isFlagForcedOff } from "@posthog/ui/features/feature-flags/devFlagOverrides";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import { isCloudTask } from "@posthog/ui/features/workspace/useWorkspace";

function featureFlags(): FeatureFlags {
  return resolveService<FeatureFlags>(FEATURE_FLAGS);
}

export const taskPreviewPortsHost: TaskPreviewPortsHost = {
  isPreviewEnabled: () =>
    import.meta.env.DEV ||
    (!isFlagForcedOff(TASK_PORT_PREVIEW_FLAG) &&
      featureFlags().isEnabled(TASK_PORT_PREVIEW_FLAG)),
  onPreviewEnabledChange: (listener) => featureFlags().onFlagsLoaded(listener),
  isCloudTask: async (task) => {
    const workspaces =
      await resolveService<HostTrpcClient>(
        HOST_TRPC_CLIENT,
      ).workspace.getAll.query();
    return isCloudTask(task, workspaces?.[task.id] ?? null);
  },
  fetchTaskRun: async (taskId, runId) => {
    const client = await getAuthenticatedClient();
    return client ? client.getTaskRun(taskId, runId) : null;
  },
};
