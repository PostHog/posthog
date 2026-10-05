// Mirrors `FeatureFlagStatusChecker.get_status` in products/feature_flags/backend/flag_status.py
export const STALE_FLAG_DEFINITION =
    'not called in the last 30 days, or older than 30 days and fully rolled out with no usage data'

// MAX_NOTIFICATIONS_PER_TEAM_PER_RUN in products/feature_flags/backend/stale_flag_notifications.py
export const MAX_STALE_FLAG_NOTIFICATIONS_PER_DAY = 10
