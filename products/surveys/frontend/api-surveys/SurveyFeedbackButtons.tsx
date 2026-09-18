import { useEffect, useRef } from 'react'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export type SurveyFeedbackRating = '1' | '2'

export function SurveyFeedbackButtons({
    value,
    submissionId,
    onChange,
    onMoreFeedback,
    loading = false,
    disabledReason,
    expanded = false,
}: {
    value?: SurveyFeedbackRating
    submissionId: string
    onChange: (rating: SurveyFeedbackRating, submissionId: string) => void
    onMoreFeedback: (submissionId: string) => void
    loading?: boolean
    disabledReason?: string
    expanded?: boolean
}): JSX.Element {
    const moreFeedbackRef = useRef<HTMLButtonElement>(null)
    const pendingFocusRating = useRef<SurveyFeedbackRating>()

    useEffect(() => {
        if (value && pendingFocusRating.current === value && !loading && !disabledReason && !expanded) {
            moreFeedbackRef.current?.focus()
            pendingFocusRating.current = undefined
        }
    }, [value, loading, disabledReason, expanded])

    return (
        <div
            className="flex w-full flex-wrap items-center justify-between gap-2"
            role="group"
            aria-label="Survey feedback"
        >
            <span className="text-secondary text-sm">
                {value === undefined ? 'Was this helpful?' : 'Thanks for your feedback.'}
            </span>
            {value === undefined ? (
                <div className="flex items-center gap-2">
                    {(
                        [
                            { value: '1', label: 'Helpful', icon: <IconThumbsUp /> },
                            { value: '2', label: 'Not helpful', icon: <IconThumbsDown /> },
                        ] as const
                    ).map((option) => (
                        <LemonButton
                            key={option.value}
                            type="secondary"
                            size="small"
                            icon={option.icon}
                            aria-label={option.label}
                            tooltip={option.label}
                            loading={loading}
                            disabledReason={disabledReason}
                            onClick={() => {
                                pendingFocusRating.current = option.value
                                onChange(option.value, submissionId)
                            }}
                            data-attr={option.value === '1' ? 'api-survey-thumbs-up' : 'api-survey-thumbs-down'}
                        />
                    ))}
                </div>
            ) : (
                <LemonButton
                    ref={moreFeedbackRef}
                    className="motion-safe:animate-fade-in"
                    size="small"
                    onClick={() => onMoreFeedback(submissionId)}
                    aria-haspopup="dialog"
                    aria-expanded={expanded}
                    disabledReason={loading ? 'Saving feedback' : disabledReason}
                    data-attr="api-survey-share-more-feedback"
                >
                    Share more feedback
                </LemonButton>
            )}
        </div>
    )
}
