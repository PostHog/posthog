import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { TraceReviewLogicProps, traceReviewLogic } from '../traceReviewLogic'

interface TraceReviewButtonProps extends TraceReviewLogicProps {
    size?: 'small' | 'xsmall'
}

export function TraceReviewButton({ traceId, size = 'xsmall' }: TraceReviewButtonProps): JSX.Element {
    const logic = traceReviewLogic({ traceId })
    const { isReviewed, traceReview, traceReviewLoading } = useValues(logic)
    const { markTraceAsReviewed, unmarkTraceAsReviewed } = useActions(logic)
    const [isHovering, setIsHovering] = useState(false)

    useEffect(() => {
        setIsHovering(false)
    }, [isReviewed])

    if (isReviewed && traceReview) {
        return (
            <Tooltip
                title={
                    <>
                        Reviewed by{' '}
                        <PersonDisplay
                            person={{
                                distinct_id: String(traceReview.reviewed_by.id),
                                properties: {
                                    email: traceReview.reviewed_by.email,
                                    first_name: traceReview.reviewed_by.first_name,
                                },
                            }}
                            withIcon="sm"
                            noPopover
                            noLink
                        />{' '}
                        <TZLabel time={traceReview.reviewed_at} />
                    </>
                }
            >
                <LemonButton
                    type="secondary"
                    size={size}
                    icon={isHovering ? <IconX /> : <IconCheck className="text-success" />}
                    onClick={unmarkTraceAsReviewed}
                    loading={traceReviewLoading}
                    onMouseEnter={() => setIsHovering(true)}
                    onMouseLeave={() => setIsHovering(false)}
                >
                    {isHovering ? 'Unmark' : 'Reviewed'}
                </LemonButton>
            </Tooltip>
        )
    }

    return (
        <LemonButton
            type="secondary"
            size={size}
            icon={<IconCheck />}
            onClick={markTraceAsReviewed}
            loading={traceReviewLoading}
            tooltip={!traceReviewLoading ? 'Mark this trace as reviewed, for other team members to know' : undefined}
        >
            Mark reviewed
        </LemonButton>
    )
}
