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

/**
 * The next value of the last-allowed-project marker after an auth state
 * change. The marker holds the project the app already showed with access
 * allowed, which is what lets isBackgroundAccessRecheck keep the app
 * mounted. A settled "blocked" or "error" result ends that grace: the next
 * "checking" for the project is a retry from the denial screen, and the app
 * must not mount before that check answers.
 */
export function nextLastAllowedProjectId(
  previous: number | null,
  state: {
    isAuthenticated: boolean;
    currentProjectId: number | null;
    accessIsCurrent: boolean;
    accessStatus: DesktopAccessStatus;
  },
): number | null {
  if (!state.isAuthenticated) return null;
  if (!state.accessIsCurrent) return previous;
  if (state.accessStatus === "allowed") return state.currentProjectId;
  if (state.accessStatus === "blocked" || state.accessStatus === "error") {
    return null;
  }
  return previous;
}
