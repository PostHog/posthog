export type ActiveScreen =
  | "onboarding"
  | "auth"
  | "desktop-access"
  | "consent"
  | "main";

/**
 * Which screen the app is on. The four pre-router screens render instead of the
 * RouterProvider, so anything the routed shell mounts is absent on them.
 */
export function resolveActiveScreen(state: {
  hasCompletedOnboarding: boolean;
  isAuthenticated: boolean;
  isBlockedByAccessPolicy: boolean;
  consentErrored: boolean;
  needsConsent: boolean;
}): ActiveScreen {
  if (!state.hasCompletedOnboarding && !state.isBlockedByAccessPolicy) {
    return "onboarding";
  }
  if (!state.isAuthenticated) return "auth";
  if (state.isBlockedByAccessPolicy) return "desktop-access";
  if (state.consentErrored || state.needsConsent) return "consent";
  return "main";
}
