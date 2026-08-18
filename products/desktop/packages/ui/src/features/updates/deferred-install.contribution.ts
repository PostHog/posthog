import { countBusyLocalSessions } from "@posthog/core/sessions/busyLocalSessions";
import { sessionStore } from "@posthog/core/sessions/sessionStore";
import {
  DEFERRED_INSTALL_COUNTDOWN_SECONDS,
  deriveDeferredInstallTransition,
  updateStore,
} from "@posthog/core/updates/updateStore";
import type { Contribution } from "@posthog/di/contribution";
import { performInstallUpdate } from "@posthog/ui/features/updates/updateStore";
import {
  UPDATES_CLIENT,
  type UpdatesClient,
} from "@posthog/ui/features/updates/updatesClient";
import { toast } from "@posthog/ui/primitives/toast";
import { inject, injectable } from "inversify";

const COUNTDOWN_TOAST_ID = "deferred-install-countdown";

/**
 * Drives "restart when idle": once the user arms it from the update banner,
 * watches local agent activity and, when the app goes idle with an update
 * ready, runs a short cancellable countdown before installing. An agent
 * starting mid-countdown sends it back to waiting; a manual restart disarms it.
 */
@injectable()
export class DeferredInstallContribution implements Contribution {
  private countdownTimer: ReturnType<typeof setInterval> | null = null;

  constructor(@inject(UPDATES_CLIENT) private readonly client: UpdatesClient) {}

  start(): void {
    updateStore.subscribe(() => this.evaluate());
    sessionStore.subscribe(() => this.evaluate());
  }

  private evaluate(): void {
    const { deferredInstallPhase, status } = updateStore.getState();
    if (deferredInstallPhase === "off") {
      // Covers the user cancelling mid-countdown from the banner or popover.
      if (this.countdownTimer) {
        this.clearTimer();
        toast.dismiss(COUNTDOWN_TOAST_ID);
      }
      return;
    }

    const transition = deriveDeferredInstallTransition({
      phase: deferredInstallPhase,
      updateStatus: status,
      busyLocalSessions: countBusyLocalSessions(
        sessionStore.getState().sessions,
      ),
    });
    if (transition === "begin-countdown") {
      this.beginCountdown();
    } else if (transition === "return-to-waiting") {
      this.clearTimer();
      toast.dismiss(COUNTDOWN_TOAST_ID);
      updateStore.getState().returnDeferredInstallToWaiting();
    } else if (transition === "disarm") {
      this.clearTimer();
      toast.dismiss(COUNTDOWN_TOAST_ID);
      updateStore.getState().disarmDeferredInstall();
    }
  }

  private beginCountdown(): void {
    this.clearTimer();
    let remaining = DEFERRED_INSTALL_COUNTDOWN_SECONDS;
    updateStore.getState().beginDeferredInstallCountdown(remaining);
    toast.info("Agents finished — restarting to update", {
      id: COUNTDOWN_TOAST_ID,
      description: `The update applies in ${remaining} seconds`,
      duration: remaining * 1000,
      action: {
        label: "Cancel",
        onClick: () => updateStore.getState().disarmDeferredInstall(),
      },
    });

    this.countdownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining > 0) {
        updateStore.getState().tickDeferredInstallCountdown(remaining);
        return;
      }
      this.clearTimer();
      // Re-check right before the trigger: an evaluate() between ticks may
      // have aborted, or an agent may have started in the final second.
      const state = updateStore.getState();
      const busy = countBusyLocalSessions(sessionStore.getState().sessions);
      if (
        state.deferredInstallPhase !== "countdown" ||
        state.status !== "ready" ||
        busy > 0
      ) {
        return;
      }
      state.disarmDeferredInstall();
      toast.dismiss(COUNTDOWN_TOAST_ID);
      void performInstallUpdate(this.client);
    }, 1000);
  }

  private clearTimer(): void {
    if (this.countdownTimer) {
      clearInterval(this.countdownTimer);
      this.countdownTimer = null;
    }
  }
}
