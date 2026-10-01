import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { SERVER_AGENT_INSTRUCTIONS_FLAG } from "@posthog/shared";
import {
  createAuthenticatedClient,
  tokenAccessors,
} from "@posthog/ui/features/auth/authClient";
import { useAuthStore } from "@posthog/ui/features/auth/store";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import {
  getEffectiveCustomInstructions,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { logger } from "@posthog/ui/shell/logger";
import { inject, injectable } from "inversify";
import { nextInstructionsMove } from "./serverAgentInstructions";

const log = logger.scope("server-agent-instructions");

/**
 * Adds the local custom instructions to "My instructions" on the server one
 * time per project, after any text already there. After that, the server adds
 * them to every cloud run, so cloud tasks stop carrying a local copy.
 */
@injectable()
export class ServerAgentInstructionsContribution implements Contribution {
  private readonly inFlight = new Set<number>();
  // Projects whose merged text is too long for the server. Cloud tasks keep
  // the local copy, and the next app start tries again.
  private readonly keptLocal = new Set<number>();

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
    if (
      settings.customInstructionsOnServerProjectIds.includes(projectId) ||
      this.inFlight.has(projectId) ||
      this.keptLocal.has(projectId)
    ) {
      return;
    }
    const { getValidAccessToken, refreshAccessToken } = tokenAccessors(
      this.hostClient,
    );
    const client = createAuthenticatedClient(
      authState,
      getValidAccessToken,
      refreshAccessToken,
    );
    if (!client) return;

    this.inFlight.add(projectId);
    try {
      const local = getEffectiveCustomInstructions(settings);
      const server = await client.getMyAgentInstructions(projectId);
      const move = nextInstructionsMove({
        // With file sync on, wait for the file snapshot, or only the
        // Simplified Technical English line would move.
        localReady:
          !settings.syncCustomInstructionsFromFile ||
          settings.syncedCustomInstructions != null,
        local,
        server,
      });
      if (move.step === "wait") return;
      if (move.step === "keepLocal") {
        this.keptLocal.add(projectId);
        log.warn("Custom instructions are too long to move to the server");
        return;
      }
      if (move.step === "upload") {
        await client.setMyAgentInstructions(projectId, move.instructions);
      }
      useSettingsStore.getState().markCustomInstructionsOnServer(projectId);
    } catch (err) {
      // Cloud tasks keep the local copy, so a failed move changes nothing.
      log.warn("Failed to move custom instructions to the server", err);
    } finally {
      this.inFlight.delete(projectId);
    }
  }
}
