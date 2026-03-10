import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { TraceReview } from './types'
import {
    getTraceReviewDisplayValue,
    getTraceReviewStatusDisplayValue,
    getTraceReviewStatusTagType,
    getTraceReviewTagType,
    getTraceReviewerName,
} from './utils'

function TraceReviewTooltipContent({ review }: { review: TraceReview }): JSX.Element {
    const reviewerName = getTraceReviewerName(review)

    return (
        <div className="max-w-80 space-y-2">
            {reviewerName ? (
                <div>
                    <span className="font-semibold">Reviewed by:</span> {reviewerName}
                </div>
            ) : null}
            {review.updated_at ? (
                <div>
                    <span className="font-semibold">Reviewed at:</span> <TZLabel time={review.updated_at} />
                </div>
            ) : null}
            {review.comment ? (
                <div className="space-y-1">
                    <div className="font-semibold">Reasoning</div>
                    <div className="whitespace-pre-wrap break-words">{review.comment}</div>
                </div>
            ) : null}
        </div>
    )
}

function wrapWithReviewTooltip(review: TraceReview, content: JSX.Element): JSX.Element {
    const reviewerName = getTraceReviewerName(review)
    const hasTooltip = !!review.comment || !!review.updated_at || !!reviewerName

    if (!hasTooltip) {
        return content
    }

    return <Tooltip title={<TraceReviewTooltipContent review={review} />}>{content}</Tooltip>
}

export function TraceReviewValue({
    review,
    size = 'small',
    className,
}: {
    review: TraceReview
    size?: 'small' | 'medium'
    className?: string
}): JSX.Element {
    return wrapWithReviewTooltip(
        review,
        <LemonTag size={size} type={getTraceReviewTagType(review)} className={className}>
            {getTraceReviewDisplayValue(review)}
        </LemonTag>
    )
}

export function TraceReviewStatusTag({
    review,
    size = 'small',
    className,
}: {
    review: TraceReview | null
    size?: 'small' | 'medium'
    className?: string
}): JSX.Element {
    const tag = (
        <LemonTag size={size} type={getTraceReviewStatusTagType(review)} className={className}>
            {getTraceReviewStatusDisplayValue(review)}
        </LemonTag>
    )

    if (!review) {
        return tag
    }

    return wrapWithReviewTooltip(review, tag)
}
