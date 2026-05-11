import type { FeatureFlagLookupKey } from 'lib/constants'

/** `keyof FEATURE_FLAGS` for `useFeatureFlag` and settings `flag` — not remote slug strings. */
export const LogsFeatureFlagKeys = {
    dropRules: 'LOGS_SETTINGS_DROP_RULES',
} as const satisfies { dropRules: FeatureFlagLookupKey }
