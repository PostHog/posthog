import type { FeatureFlagLookupKey } from 'lib/constants'

/** `keyof FEATURE_FLAGS` for `useFeatureFlag` and settings `flag` — not remote slug strings. */
export const LogsFeatureFlagKeys = {
    retentionRules: 'LOGS_SETTINGS_RETENTION_RULES',
} as const satisfies {
    retentionRules: FeatureFlagLookupKey
}
