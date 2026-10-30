import type { ReviewerRemovalReasonEnumApi } from 'products/signals/frontend/generated/api.schemas'

/**
 * The reasons a person can give when they remove a reviewer, worded for their own row or a teammate's.
 * The list stays short on purpose. Research reads the reason when it picks reviewers for later reports.
 */
export function reviewerRemovalReasonOptions(
    isSelf: boolean
): { value: ReviewerRemovalReasonEnumApi; label: string }[] {
    return [
        { value: 'already_covered', label: 'Someone else is on it' },
        { value: 'wrong_area', label: isSelf ? 'Not my area' : 'Not their area' },
        {
            value: 'unavailable',
            label: isSelf ? "I don't have bandwidth right now" : "They don't have bandwidth right now",
        },
    ]
}
