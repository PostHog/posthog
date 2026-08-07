import type { FeatureFlagLookupKey } from 'lib/constants'

/** `keyof FEATURE_FLAGS` for `useFeatureFlag` and settings `flag` — not remote slug strings. */
export const LogsFeatureFlagKeys = {
    dropRules: 'LOGS_SETTINGS_DROP_RULES',
    metricRules: 'LOGS_METRIC_RULES',
    retentionRules: 'LOGS_SETTINGS_RETENTION_RULES',
} as const satisfies {
    dropRules: FeatureFlagLookupKey
    metricRules: FeatureFlagLookupKey
    retentionRules: FeatureFlagLookupKey
}
