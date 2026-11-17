import type { TaskDefaults } from "@posthog/api-client/posthog-client";
import type {
  DefaultInitialTaskMode,
  TaskDefaultsSyncState,
} from "./settingsStore";

export interface TaskDefaultsSync {
  upload: Partial<Record<keyof TaskDefaults, boolean>>;
  // Set when the server holds a newer "always create pull requests" value.
  pullAutoPublishCloudRuns: boolean | null;
  pullInitialTaskMode: DefaultInitialTaskMode | null;
  synced: TaskDefaultsSyncState;
}

/**
 * What to sync between Desktop and the task defaults on the server for one
 * project. Both values stay in step both ways: the side that changed since the
 * last sync wins, and on the first sync the server wins. An unset "always
 * create pull requests" takes the Desktop value. An unset "Start in plan mode"
 * reads as off, so plan mode stays off until a person turns it on.
 */
export function nextTaskDefaultsSync(input: {
  server: TaskDefaults;
  localAutoPublishCloudRuns: boolean;
  localInitialTaskMode: DefaultInitialTaskMode;
  synced: TaskDefaultsSyncState | undefined;
}): TaskDefaultsSync {
  const { server, localAutoPublishCloudRuns, localInitialTaskMode, synced } =
    input;
  const upload: TaskDefaultsSync["upload"] = {};

  const autoPublish = syncFlag({
    remote: server.auto_publish_cloud_runs,
    local: localAutoPublishCloudRuns,
    last: synced?.autoPublishCloudRuns,
    unsetRemote: "upload",
  });
  if (autoPublish.upload !== undefined) {
    upload.auto_publish_cloud_runs = autoPublish.upload;
  }

  const localPlan = localInitialTaskMode === "plan";
  const planMode = syncFlag({
    remote: server.start_in_plan_mode,
    local: localPlan,
    last: synced?.startInPlanMode,
    unsetRemote: "off",
  });
  if (planMode.upload !== undefined) {
    upload.start_in_plan_mode = planMode.upload;
  }

  return {
    upload,
    pullAutoPublishCloudRuns:
      autoPublish.agreed !== localAutoPublishCloudRuns
        ? autoPublish.agreed
        : null,
    pullInitialTaskMode:
      planMode.agreed !== localPlan
        ? planMode.agreed
          ? "plan"
          : "last_used"
        : null,
    synced: {
      autoPublishCloudRuns: autoPublish.agreed,
      startInPlanMode: planMode.agreed,
    },
  };
}

function syncFlag(input: {
  remote: boolean | null;
  local: boolean;
  last: boolean | undefined;
  unsetRemote: "upload" | "off";
}): { upload?: boolean; agreed: boolean } {
  const { local, last } = input;
  if (input.remote === null && input.unsetRemote === "upload") {
    return { upload: local, agreed: local };
  }
  const remote = input.remote ?? false;
  if (last === undefined) {
    return { agreed: remote };
  }
  if (local !== last) {
    return { upload: local, agreed: local };
  }
  return { agreed: remote };
}
