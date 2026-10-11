import type { ReviewRecentReviewApi, ReviewTriggerReviewModeEnumApi } from './generated/api.schemas'

export const REVIEW_MODE_LABEL: Record<ReviewTriggerReviewModeEnumApi, string> = {
    flash: 'Standard',
    full: 'Deep',
}

export function reviewTitle(
    review: Pick<ReviewRecentReviewApi, 'pr_title' | 'repository' | 'pr_number' | 'head_branch'>
): string {
    return review.pr_title ?? `${review.repository}#${review.pr_number ?? review.head_branch}`
}

function withCounter(label: string, done: number | null, total: number | null): string {
    return done !== null && total !== null && total > 0 ? `${label} ${done}/${total}` : label
}

export function runningStageLabel(review: ReviewRecentReviewApi): string {
    if (review.resolution?.resolution_status === 'resolving') {
        return withCounter('Resolving', review.resolution.done, review.resolution.total)
    }
    if (!review.progress) {
        return 'Starting'
    }
    const { review_stage, done, total } = review.progress
    switch (review_stage) {
        case 'fetching':
        case 'chunking':
        case 'single_agent_preparing':
            return 'Preparing'
        case 'selecting':
            return 'Picking perspectives'
        case 'reviewing':
        case 'single_agent_reviewing':
            return withCounter('Reviewing', done, total)
        case 'deduplicating':
            return 'Merging findings'
        case 'validating':
            return withCounter('Validating', done, total)
        case 'finalizing':
        case 'single_agent_finalizing':
            return 'Finalizing'
    }
}
