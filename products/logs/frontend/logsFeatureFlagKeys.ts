import type { FeatureFlagLookupKey } from 'lib/constants'

/** `keyof FEATURE_FLAGS` for `useFeatureFlag` and settings `flag` — not remote slug strings. */
export const LogsFeatureFlagKeys = {
    samplingRules: 'LOGS_SAMPLING_RULES',
} as const satisfies { samplingRules: FeatureFlagLookupKey }
