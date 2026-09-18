import { SurveyQuestion, SurveyQuestionType } from 'posthog-js'
import { useEffect, useRef } from 'react'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ratingValues } from './surveyQuestions'

export function SurveyFeedbackButtons({
    question,
    value,
    accepted = value !== undefined,
    requiresCompletion = false,
    onEdit,
    submissionId,
    onChange,
    onMoreFeedback,
    loading = false,
    disabledReason,
    expanded = false,
}: {
    question: Extract<SurveyQuestion, { type: typeof SurveyQuestionType.Rating }>
    value?: string
    accepted?: boolean
    requiresCompletion?: boolean
    onEdit?: () => void
    submissionId: string
    onChange: (rating: string, submissionId: string) => void
    onMoreFeedback: (submissionId: string) => void
    loading?: boolean
    disabledReason?: string
    expanded?: boolean
}): JSX.Element {
    const moreFeedbackRef = useRef<HTMLButtonElement>(null)
    const pendingFocusRating = useRef<string>()
    const editFocus = useRef(false)
    const selectedButtonRef = useRef<HTMLButtonElement>(null)
    const showSummary = accepted && value !== undefined

    useEffect(() => {
        if (showSummary && pendingFocusRating.current === value && !loading && !disabledReason && !expanded) {
            moreFeedbackRef.current?.focus()
            pendingFocusRating.current = undefined
        }
        if (!showSummary && editFocus.current) {
            selectedButtonRef.current?.focus()
            editFocus.current = false
        }
    }, [value, showSummary, loading, disabledReason, expanded])

    return (
        <div
            className="flex w-full flex-wrap items-center justify-between gap-2"
            role="group"
            aria-label={question.question}
        >
            <span className="text-secondary text-sm">
                {showSummary
                    ? question.display === 'number'
                        ? `You rated this ${value}/${question.scale}`
                        : `Selected: ${value === '1' ? question.lowerBoundLabel || 'Thumbs up' : question.upperBoundLabel || 'Thumbs down'}`
                    : question.question}
                {!showSummary && question.description && <span className="block text-xs">{question.description}</span>}
                {showSummary && requiresCompletion && (
                    <span className="block text-xs">Complete the survey to send your rating.</span>
                )}
            </span>
            {!showSummary ? (
                <div className={question.display === 'number' ? 'w-full space-y-2' : 'max-w-full space-y-2'}>
                    <div className="flex flex-wrap items-center gap-1">
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
                                    ref={value === rating ? selectedButtonRef : undefined}
                                    active={value === rating}
                                    aria-pressed={value === rating}
                                    center
                                    className={
                                        question.display === 'number'
                                            ? 'min-w-8 flex-1 border border-primary'
                                            : undefined
                                    }
                                    data-attr={
                                        question.display === 'emoji'
                                            ? rating === '1'
                                                ? 'api-survey-thumbs-up'
                                                : 'api-survey-thumbs-down'
                                            : 'api-survey-rating'
                                    }
                                    type={question.display === 'number' ? 'tertiary' : 'secondary'}
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
                <div className="flex items-center gap-2 motion-safe:animate-fade-in">
                    {onEdit && (
                        <LemonButton
                            size="small"
                            disabledReason={loading ? 'Saving feedback' : disabledReason}
                            onClick={() => {
                                editFocus.current = true
                                onEdit()
                            }}
                        >
                            Change
                        </LemonButton>
                    )}
                    <LemonButton
                        ref={moreFeedbackRef}
                        size="small"
                        onClick={() => onMoreFeedback(submissionId)}
                        aria-haspopup="dialog"
                        aria-expanded={expanded}
                        disabledReason={loading ? 'Saving feedback' : disabledReason}
                        data-attr="api-survey-share-more-feedback"
                    >
                        Share more feedback
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
