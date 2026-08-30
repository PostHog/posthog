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

/**
 * True while the access check re-runs for a project the app already showed on
 * the denial screen. A retry ("Check again"), a token refresh, or an org or
 * project switch flips the status back to "checking"; without this grace the
 * app drops the denial screen for the onboarding flow until the check settles
 * again. It mirrors isBackgroundAccessRecheck, but holds the denial screen
 * rather than the running app.
 */
export function isBlockedAccessRecheck(
  lastBlockedProjectId: number | null,
  currentProjectId: number | null,
  accessStatus: DesktopAccessStatus,
): boolean {
  return (
    accessStatus === "checking" &&
    lastBlockedProjectId !== null &&
    lastBlockedProjectId === currentProjectId
  );
}

/**
 * The next value of the last-blocked-project marker after an auth state
 * change. The marker holds the project the app already showed on the denial
 * screen, which is what lets isBlockedAccessRecheck keep that screen up
 * through a recheck. A settled "allowed" result clears it, and sign-out
 * clears it; a "checking" flip carries it so the recheck keeps the screen.
 */
export function nextLastBlockedProjectId(
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
  if (state.accessStatus === "blocked" || state.accessStatus === "error") {
    return state.currentProjectId;
  }
  if (state.accessStatus === "allowed") return null;
  return previous;
}
