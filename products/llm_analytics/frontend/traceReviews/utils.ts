import type { TraceReview } from './types'

export function formatNumericTraceReviewScore(value: string | number | null | undefined): string {
    if (value === null || value === undefined || value === '') {
        return ''
    }

    return String(value)
        .replace(/(\.\d*?)0+$/, '$1')
        .replace(/\.$/, '')
}

export function getTraceReviewDisplayValue(review: TraceReview): string {
    if (review.score_kind === 'label' && review.score_label) {
        return review.score_label
    }

    if (review.score_kind === 'numeric' && review.score_numeric !== null) {
        return formatNumericTraceReviewScore(review.score_numeric)
    }

    return 'Reviewed'
}

export function getTraceReviewStatusDisplayValue(review: TraceReview | null): string {
    if (!review) {
        return 'Not reviewed'
    }

    const reviewValue = getTraceReviewDisplayValue(review)

    return reviewValue === 'Reviewed' ? 'Reviewed' : `Reviewed: ${reviewValue}`
}

export function getTraceReviewTagType(review: TraceReview): 'success' | 'danger' | 'completion' | 'muted' {
    if (review.score_kind === 'label') {
        return review.score_label === 'good' ? 'success' : 'danger'
    }

    if (review.score_kind === 'numeric' && review.score_numeric !== null) {
        return 'completion'
    }

    return 'muted'
}

export function getTraceReviewStatusTagType(review: TraceReview | null): 'success' | 'danger' | 'completion' | 'muted' {
    if (!review) {
        return 'muted'
    }

    if (review.score_kind === null) {
        return 'success'
    }

    return getTraceReviewTagType(review)
}

export function getTraceReviewerName(review: TraceReview): string | null {
    const reviewer = review.reviewed_by

    if (!reviewer) {
        return null
    }

    if (reviewer.first_name) {
        return reviewer.first_name
    }

    if (reviewer.email) {
        return reviewer.email
    }

    if (reviewer.distinct_id) {
        return reviewer.distinct_id
    }

    return null
}
