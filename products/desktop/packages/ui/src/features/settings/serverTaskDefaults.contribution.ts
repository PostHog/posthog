import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { SERVER_TASK_DEFAULTS_FLAG } from "@posthog/shared";
import { createAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStore } from "@posthog/ui/features/auth/store";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { logger } from "@posthog/ui/shell/logger";
import { inject, injectable } from "inversify";
import { nextTaskDefaultsSync } from "./serverTaskDefaults";

const log = logger.scope("server-task-defaults");

/**
 * Keeps the task defaults on the server in step with Desktop for each project
 * the person opens. Desktop still starts tasks from its local settings, so a
 * failed request changes nothing for the person.
 */
@injectable()
export class ServerTaskDefaultsContribution implements Contribution {
  private readonly inFlight = new Set<number>();
  private readonly rerun = new Set<number>();

  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
    @inject(FEATURE_FLAGS)
    private readonly flags: FeatureFlags,
  ) {}

  start(): void {
    this.flags.onFlagsLoaded(() => void this.reconcile(true));
    useAuthStore.subscribe((state, prev) => {
      if (
        state.authState.currentProjectId !== prev.authState.currentProjectId ||
        state.authState.status !== prev.authState.status
      ) {
        void this.reconcile(true);
      }
    });
    useSettingsStore.subscribe((state, prev) => {
      if (
        state._hasHydrated !== prev._hasHydrated ||
        state.autoPublishCloudRuns !== prev.autoPublishCloudRuns
      ) {
        void this.reconcile(false);
      }
    });
    void this.reconcile(true);
  }

  // `fetchAlways` reads the server even when Desktop has nothing new, to pick
  // up a change made on web.
  private async reconcile(fetchAlways: boolean): Promise<void> {
    if (!this.flags.isEnabled(SERVER_TASK_DEFAULTS_FLAG)) return;
    const settings = useSettingsStore.getState();
    const authState = useAuthStore.getState().authState;
    const projectId = authState.currentProjectId;
    if (!settings._hasHydrated || projectId == null) return;
    const synced = settings.taskDefaultsOnServer[String(projectId)];
    const local = settings.autoPublishCloudRuns;
    if (
      !fetchAlways &&
      synced?.planModeOffered &&
      synced.autoPublishCloudRuns === local
    ) {
      return;
    }
    if (this.inFlight.has(projectId)) {
      this.rerun.add(projectId);
      return;
    }
    const client = createAuthenticatedClient(
      authState,
      () =>
        this.hostClient.auth.getValidAccessToken
          .query()
          .then((r) => r.accessToken),
      () =>
        this.hostClient.auth.refreshAccessToken
          .mutate()
          .then((r) => r.accessToken),
    );
    if (!client) return;

    this.inFlight.add(projectId);
    try {
      const { taskDefaults } = await client.getMyTaskRunConfig(projectId);
      const sync = nextTaskDefaultsSync({
        server: taskDefaults,
        localAutoPublishCloudRuns: local,
        localInitialTaskMode: settings.defaultInitialTaskMode,
        synced,
      });
      if (Object.keys(sync.upload).length > 0) {
        await client.setMyTaskDefaults(projectId, sync.upload);
      }
      const store = useSettingsStore.getState();
      if (store.autoPublishCloudRuns !== local) {
        // The person changed the setting while the request ran. The rerun
        // sends that change.
        this.rerun.add(projectId);
        store.setTaskDefaultsOnServer(projectId, {
          ...sync.synced,
          autoPublishCloudRuns: local,
        });
        return;
      }
      // Record the sync before the local value changes, so that change does
      // not read as a Desktop edit.
      store.setTaskDefaultsOnServer(projectId, sync.synced);
      if (sync.pullAutoPublishCloudRuns !== null) {
        store.setAutoPublishCloudRuns(sync.pullAutoPublishCloudRuns);
      }
    } catch (err) {
      log.warn("Failed to sync task defaults with the server", err);
    } finally {
      this.inFlight.delete(projectId);
      if (this.rerun.delete(projectId)) {
        void this.reconcile(false);
      }
    }
  }
}
