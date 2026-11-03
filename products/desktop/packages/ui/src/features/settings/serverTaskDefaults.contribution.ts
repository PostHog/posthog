import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { createAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStore } from "@posthog/ui/features/auth/store";
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
  ) {}

  start(): void {
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
        state.autoPublishCloudRuns !== prev.autoPublishCloudRuns ||
        state.defaultInitialTaskMode !== prev.defaultInitialTaskMode
      ) {
        void this.reconcile(false);
      }
    });
    void this.reconcile(true);
  }

  // `fetchAlways` reads the server even when Desktop has nothing new, to pick
  // up a change made on web.
  private async reconcile(fetchAlways: boolean): Promise<void> {
    const settings = useSettingsStore.getState();
    const authState = useAuthStore.getState().authState;
    const projectId = authState.currentProjectId;
    if (!settings._hasHydrated || projectId == null) return;
    const synced = settings.taskDefaultsOnServer[String(projectId)];
    const local = settings.autoPublishCloudRuns;
    const localMode = settings.defaultInitialTaskMode;
    if (
      !fetchAlways &&
      synced?.autoPublishCloudRuns === local &&
      synced.startInPlanMode === (localMode === "plan")
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
        localInitialTaskMode: localMode,
        synced,
      });
      if (Object.keys(sync.upload).length > 0) {
        await client.setMyTaskDefaults(projectId, sync.upload);
      }
      // The local setting is shared by every project, so a reply for a
      // project the person has left must not change it. The sync for the
      // current project runs on its own.
      if (useAuthStore.getState().authState.currentProjectId !== projectId) {
        return;
      }
      const store = useSettingsStore.getState();
      if (
        store.autoPublishCloudRuns !== local ||
        store.defaultInitialTaskMode !== localMode
      ) {
        // The person changed the setting while the request ran. The rerun
        // sends that change.
        this.rerun.add(projectId);
        store.setTaskDefaultsOnServer(projectId, {
          ...sync.synced,
          autoPublishCloudRuns: local,
          startInPlanMode: localMode === "plan",
        });
        return;
      }
      // Record the sync before the local value changes, so that change does
      // not read as a Desktop edit.
      store.setTaskDefaultsOnServer(projectId, sync.synced);
      if (sync.pullAutoPublishCloudRuns !== null) {
        store.setAutoPublishCloudRuns(sync.pullAutoPublishCloudRuns);
      }
      if (sync.pullInitialTaskMode !== null) {
        const pulledPlan = sync.pullInitialTaskMode === "plan";
        for (const [otherId, other] of Object.entries(
          store.taskDefaultsOnServer,
        )) {
          if (
            otherId !== String(projectId) &&
            other.startInPlanMode !== undefined
          ) {
            store.setTaskDefaultsOnServer(Number(otherId), {
              ...other,
              startInPlanMode: pulledPlan,
            });
          }
        }
        store.setDefaultInitialTaskMode(sync.pullInitialTaskMode);
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
