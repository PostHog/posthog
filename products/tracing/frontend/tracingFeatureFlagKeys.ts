import type { FeatureFlagLookupKey } from 'lib/constants'

/** `keyof FEATURE_FLAGS` for `useFeatureFlag` and settings `flag` — not remote slug strings. */
export const TracingFeatureFlagKeys = {
    retentionRules: 'TRACING_SETTINGS_RETENTION_RULES',
    // Traces reuse the logs entitlement, so they reuse its flag too.
    customRetention: 'LOGS_SETTINGS_CUSTOM_RETENTION',
} as const satisfies {
    retentionRules: FeatureFlagLookupKey
    customRetention: FeatureFlagLookupKey
}
