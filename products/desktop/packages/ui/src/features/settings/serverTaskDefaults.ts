import type { TaskDefaults } from "@posthog/api-client/posthog-client";
import type {
  DefaultInitialTaskMode,
  TaskDefaultsSyncState,
} from "./settingsStore";

export interface TaskDefaultsSync {
  upload: Partial<Record<keyof TaskDefaults, boolean>>;
  // Set when the server holds a newer "always create pull requests" value.
  pullAutoPublishCloudRuns: boolean | null;
  synced: TaskDefaultsSyncState;
}

/**
 * What to sync between Desktop and the task defaults on the server for one
 * project. A value nobody set on the server takes the Desktop value, so Desktop
 * users keep what they have. "Start in" is offered once and stays local after.
 * "Always create pull requests" stays in step both ways: the side that changed
 * since the last sync wins.
 */
export function nextTaskDefaultsSync(input: {
  server: TaskDefaults;
  localAutoPublishCloudRuns: boolean;
  localInitialTaskMode: DefaultInitialTaskMode;
  synced: TaskDefaultsSyncState | undefined;
}): TaskDefaultsSync {
  const { server, localAutoPublishCloudRuns: local, synced } = input;
  const upload: TaskDefaultsSync["upload"] = {};

  if (
    !synced?.planModeOffered &&
    server.start_in_plan_mode === null &&
    input.localInitialTaskMode === "plan"
  ) {
    upload.start_in_plan_mode = true;
  }

  let agreed = local;
  let pull: boolean | null = null;
  const remote = server.auto_publish_cloud_runs;
  if (remote === null) {
    upload.auto_publish_cloud_runs = local;
  } else if (synced === undefined) {
    // First sync on this device: a value already on the server was chosen on purpose.
    agreed = remote;
  } else if (local !== synced.autoPublishCloudRuns) {
    upload.auto_publish_cloud_runs = local;
  } else {
    agreed = remote;
  }
  if (agreed !== local) {
    pull = agreed;
  }

  return {
    upload,
    pullAutoPublishCloudRuns: pull,
    synced: { autoPublishCloudRuns: agreed, planModeOffered: true },
  };
}
