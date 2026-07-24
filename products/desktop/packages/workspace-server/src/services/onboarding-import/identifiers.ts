import type { OnboardingImportSummary } from "./schemas";

export const ONBOARDING_IMPORT_SERVICE = Symbol.for(
  "posthog.workspace.onboardingImport",
);

export interface OnboardingImportService {
  getSummary(): Promise<OnboardingImportSummary>;
}
