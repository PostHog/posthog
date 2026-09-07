import { ReviewModeEnumApi } from './generated/api.schemas'

// The repo settings and the activity log both name the review mode, so they read from one map.
export const REVIEW_MODE_LABELS: Record<ReviewModeEnumApi, string> = {
    [ReviewModeEnumApi.All]: 'All PRs',
    [ReviewModeEnumApi.Label]: 'Label-triggered',
}
