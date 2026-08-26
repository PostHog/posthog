import type { FeatureFlagLookupKey } from 'lib/constants'

/** `keyof FEATURE_FLAGS` for `useFeatureFlag` and settings `flag` — not remote slug strings. */
export const LogsFeatureFlagKeys = {
    metricRules: 'LOGS_METRIC_RULES',
    retentionRules: 'LOGS_SETTINGS_RETENTION_RULES',
} as const satisfies {
    metricRules: FeatureFlagLookupKey
    retentionRules: FeatureFlagLookupKey
}
