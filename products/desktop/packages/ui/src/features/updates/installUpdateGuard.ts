import { sessionStore } from "@posthog/core/sessions/sessionStore";
import { listWorkingLocalSessions } from "@posthog/core/sessions/workingSessions";
import { useUpdateInterruptStore } from "@posthog/ui/features/updates/updateInterruptStore";

/**
 * Every restart-to-update trigger goes through here: runs the install
 * directly unless local agent turns are in flight, in which case the
 * interrupt dialog takes over and runs it on confirm.
 */
export function requestInstallUpdate(runInstall: () => void): void {
  const working = listWorkingLocalSessions(sessionStore.getState().sessions);
  if (working.length === 0) {
    runInstall();
    return;
  }
  useUpdateInterruptStore.getState().open(runInstall);
}
