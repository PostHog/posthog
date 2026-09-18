import { SurveyQuestion, SurveyQuestionType } from 'posthog-js'
import { useEffect, useRef } from 'react'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ratingValues } from './surveyQuestions'

export function SurveyFeedbackButtons({
    question,
    value,
    submissionId,
    onChange,
    onMoreFeedback,
    loading = false,
    disabledReason,
    expanded = false,
}: {
    question: Extract<SurveyQuestion, { type: typeof SurveyQuestionType.Rating }>
    value?: string
    submissionId: string
    onChange: (rating: string, submissionId: string) => void
    onMoreFeedback: (submissionId: string) => void
    loading?: boolean
    disabledReason?: string
    expanded?: boolean
}): JSX.Element {
    const moreFeedbackRef = useRef<HTMLButtonElement>(null)
    const pendingFocusRating = useRef<string>()

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
            aria-label={question.question}
        >
            <span className="text-secondary text-sm">
                {value === undefined ? question.question : 'Thanks for your feedback.'}
                {value === undefined && question.description && (
                    <span className="block text-xs">{question.description}</span>
                )}
            </span>
            {value === undefined ? (
                <div className="max-w-full space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                        {ratingValues(question.scale).map((rating) => {
                            const label =
                                question.display === 'emoji'
                                    ? rating === '1'
                                        ? question.lowerBoundLabel || 'Thumbs up'
                                        : question.upperBoundLabel || 'Thumbs down'
                                    : rating
                            return (
                                <LemonButton
                                    key={rating}
                                    data-attr={
                                        question.display === 'emoji'
                                            ? rating === '1'
                                                ? 'api-survey-thumbs-up'
                                                : 'api-survey-thumbs-down'
                                            : 'api-survey-rating'
                                    }
                                    type="secondary"
                                    size="small"
                                    icon={
                                        question.display === 'emoji' ? (
                                            rating === '1' ? (
                                                <IconThumbsUp />
                                            ) : (
                                                <IconThumbsDown />
                                            )
                                        ) : undefined
                                    }
                                    aria-label={label}
                                    tooltip={question.display === 'emoji' ? label : undefined}
                                    loading={loading}
                                    disabledReason={disabledReason}
                                    onClick={() => {
                                        pendingFocusRating.current = rating
                                        onChange(rating, submissionId)
                                    }}
                                >
                                    {question.display === 'number' ? rating : undefined}
                                </LemonButton>
                            )
                        })}
                    </div>
                    {question.display === 'number' && (
                        <div className="flex justify-between gap-4 text-xs text-secondary">
                            <span>{question.lowerBoundLabel}</span>
                            <span>{question.upperBoundLabel}</span>
                        </div>
                    )}
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
