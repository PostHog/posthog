import type { FeatureFlagLookupKey } from 'lib/constants'

/** `keyof FEATURE_FLAGS` for `useFeatureFlag` and settings `flag` — not remote slug strings. */
export const TracingFeatureFlagKeys = {
    retentionRules: 'TRACING_SETTINGS_RETENTION_RULES',
    // Custom periods reuse the Logs flag, so both products offer the same period options.
    customRetention: 'LOGS_SETTINGS_CUSTOM_RETENTION',
} as const satisfies {
    retentionRules: FeatureFlagLookupKey
    customRetention: FeatureFlagLookupKey
}
