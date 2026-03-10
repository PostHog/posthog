import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { TraceReview } from './types'
import { getTraceReviewDisplayValue, getTraceReviewTagType, getTraceReviewerName } from './utils'

export function TraceReviewValue({
    review,
    size = 'small',
}: {
    review: TraceReview
    size?: 'small' | 'medium'
}): JSX.Element {
    const tag = (
        <LemonTag size={size} type={getTraceReviewTagType(review)}>
            {getTraceReviewDisplayValue(review)}
        </LemonTag>
    )

    const reviewerName = getTraceReviewerName(review)
    const hasTooltip = !!review.comment || !!review.updated_at || !!reviewerName

    if (!hasTooltip) {
        return tag
    }

    return (
        <Tooltip
            title={
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
                            <div className="font-semibold">Comment</div>
                            <div className="whitespace-pre-wrap break-words">{review.comment}</div>
                        </div>
                    ) : null}
                </div>
            }
        >
            {tag}
        </Tooltip>
    )
}
