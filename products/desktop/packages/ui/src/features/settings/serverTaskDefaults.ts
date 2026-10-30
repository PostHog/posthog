import type { TaskDefaults } from "@posthog/api-client/posthog-client";
import type { TaskDefaultsSyncState } from "./settingsStore";

export interface TaskDefaultsSync {
  upload: Partial<Record<keyof TaskDefaults, boolean>>;
  // Set when the server holds a newer "always create pull requests" value.
  pullAutoPublishCloudRuns: boolean | null;
  synced: TaskDefaultsSyncState;
}

/**
 * What to sync between Desktop and the task defaults on the server for one
 * project. A value nobody set on the server takes the Desktop value, so Desktop
 * users keep what they have. "Start in" stays local. "Always create pull
 * requests" stays in step both ways: the side that changed since the last sync
 * wins.
 */
export function nextTaskDefaultsSync(input: {
  server: TaskDefaults;
  localAutoPublishCloudRuns: boolean;
  synced: TaskDefaultsSyncState | undefined;
}): TaskDefaultsSync {
  const { server, localAutoPublishCloudRuns: local, synced } = input;
  const upload: TaskDefaultsSync["upload"] = {};

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
    synced: { autoPublishCloudRuns: agreed },
  };
}
