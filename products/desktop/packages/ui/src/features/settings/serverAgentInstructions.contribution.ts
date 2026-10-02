import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { SERVER_AGENT_INSTRUCTIONS_FLAG } from "@posthog/shared";
import { createAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStore } from "@posthog/ui/features/auth/store";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { logger } from "@posthog/ui/shell/logger";
import { inject, injectable } from "inversify";
import {
  getLocalInstructionsContent,
  nextServerInstructions,
} from "./serverAgentInstructions";

const log = logger.scope("server-agent-instructions");

/**
 * Keeps "My instructions" on the server in step with the Desktop custom
 * instructions for each project the person opens. The first upload adds the
 * text after any text already there. Later Desktop edits replace that part.
 * While the server holds the current text, cloud tasks do not carry a copy.
 */
@injectable()
export class ServerAgentInstructionsContribution implements Contribution {
  private readonly inFlight = new Set<number>();
  // The local text per project that is too long to merge on the server.
  // Cloud tasks keep the local copy until that text changes.
  private readonly keptLocal = new Map<number, string>();

  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
    @inject(FEATURE_FLAGS)
    private readonly flags: FeatureFlags,
  ) {}

  start(): void {
    const run = () => void this.reconcile();
    this.flags.onFlagsLoaded(run);
    useSettingsStore.subscribe(run);
    useAuthStore.subscribe(run);
    run();
  }

  private async reconcile(): Promise<void> {
    if (!this.flags.isEnabled(SERVER_AGENT_INSTRUCTIONS_FLAG)) return;
    const settings = useSettingsStore.getState();
    const authState = useAuthStore.getState().authState;
    const projectId = authState.currentProjectId;
    if (!settings._hasHydrated || projectId == null) return;
    const local = getLocalInstructionsContent(settings);
    if (local === null) return;
    const uploaded = settings.customInstructionsOnServer[String(projectId)];
    if (
      uploaded === local ||
      this.inFlight.has(projectId) ||
      this.keptLocal.get(projectId) === local
    ) {
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
      const server = await client.getMyAgentInstructions(projectId);
      const update = nextServerInstructions({
        server,
        previous: uploaded,
        local,
      });
      if (update.step === "keepLocal") {
        this.keptLocal.set(projectId, local);
        log.warn("Custom instructions are too long to move to the server");
        return;
      }
      if (update.step === "upload") {
        await client.setMyAgentInstructions(projectId, update.instructions);
      }
      // This store update runs reconcile again, which uploads an edit made
      // while this request was in flight.
      useSettingsStore
        .getState()
        .setCustomInstructionsOnServer(projectId, local);
    } catch (err) {
      // Cloud tasks keep the local copy, so a failed move changes nothing.
      log.warn("Failed to move custom instructions to the server", err);
    } finally {
      this.inFlight.delete(projectId);
    }
  }
}
