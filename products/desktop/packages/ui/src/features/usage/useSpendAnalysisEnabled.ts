import { SPEND_ANALYSIS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

export function useSpendAnalysisEnabled(): boolean {
  return useFeatureFlag(SPEND_ANALYSIS_FLAG) || import.meta.env.DEV;
}
