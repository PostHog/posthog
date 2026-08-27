import type { AuthState } from "@posthog/core/auth/schemas";

type DesktopAccessStatus = AuthState["desktopAccess"]["status"];

/**
 * True while the desktop access check re-runs for a project the app already
 * showed with access allowed. Token refreshes and session recovery flip the
 * access status back to "checking"; gating the app on that flip replaces the
 * running app with the full-window loading screen. A first load (no
 * previously allowed project) and a project change still gate, and a settled
 * "blocked" or "error" result still swaps to the access screen.
 */
export function isBackgroundAccessRecheck(
  lastAllowedProjectId: number | null,
  currentProjectId: number | null,
  accessStatus: DesktopAccessStatus,
): boolean {
  return (
    accessStatus === "checking" &&
    lastAllowedProjectId !== null &&
    lastAllowedProjectId === currentProjectId
  );
}
