import type { OrgConsent } from "@posthog/ui/features/consent/useOrgConsent";

type ConsentStatus = OrgConsent["status"];

/**
 * True while the organization consent check re-runs for an organization the
 * app already showed with consent satisfied. Consent returns to "loading"
 * whenever the current-user or beta-terms query has no data, and a project
 * switch or a logout drops both from the query cache; gating the app on that
 * flip replaces the running app with the full-window loading screen. A first
 * load (no previously satisfied organization) and an organization change
 * still gate, and a settled "resolved but not satisfied" or "error" result
 * still swaps to the consent screen.
 */
export function isBackgroundConsentRecheck(
  lastSatisfiedOrgId: string | null,
  currentOrgId: string | null,
  consentStatus: ConsentStatus,
): boolean {
  return (
    consentStatus === "loading" &&
    lastSatisfiedOrgId !== null &&
    lastSatisfiedOrgId === currentOrgId
  );
}

/**
 * The next value of the last-satisfied-organization marker after a consent
 * change. The marker holds the organization the app already showed with
 * consent satisfied, which is what lets isBackgroundConsentRecheck keep the
 * app mounted. A settled unsatisfied or "error" result ends that grace: the
 * next "loading" for the organization is a retry from the consent screen, and
 * the app must not mount before that check answers.
 */
export function nextLastSatisfiedOrgId(
  previous: string | null,
  state: {
    isAuthenticated: boolean;
    currentOrgId: string | null;
    consentStatus: ConsentStatus;
    consentSatisfied: boolean;
  },
): string | null {
  if (!state.isAuthenticated) return null;
  if (state.consentStatus === "resolved") {
    return state.consentSatisfied ? state.currentOrgId : null;
  }
  if (state.consentStatus === "error") return null;
  return previous;
}
