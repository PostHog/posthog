import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export type SurveyFeedbackRating = '1' | '2'

export function SurveyFeedbackButtons({
    value,
    onChange,
    onMoreFeedback,
    loading = false,
    disabledReason,
    expanded = false,
}: {
    value?: SurveyFeedbackRating
    onChange: (rating: SurveyFeedbackRating) => void
    onMoreFeedback: () => void
    loading?: boolean
    disabledReason?: string
    expanded?: boolean
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Was this helpful?">
            <span className="text-secondary text-sm">Was this helpful?</span>
            {(
                [
                    { value: '1', label: 'Helpful', icon: <IconThumbsUp /> },
                    { value: '2', label: 'Not helpful', icon: <IconThumbsDown /> },
                ] as const
            ).map((option) => (
                <LemonButton
                    key={option.value}
                    type={value === option.value ? 'primary' : 'secondary'}
                    size="small"
                    icon={option.icon}
                    active={value === option.value}
                    aria-label={option.label}
                    aria-pressed={value === option.value}
                    tooltip={option.label}
                    loading={loading}
                    disabledReason={disabledReason}
                    onClick={() => value !== option.value && onChange(option.value)}
                    data-attr={option.value === '1' ? 'api-survey-thumbs-up' : 'api-survey-thumbs-down'}
                />
            ))}
            <LemonButton
                size="small"
                onClick={onMoreFeedback}
                aria-haspopup="dialog"
                aria-expanded={expanded}
                disabledReason={loading ? 'Saving feedback' : disabledReason}
                data-attr="api-survey-share-more-feedback"
            >
                Share more feedback
            </LemonButton>
        </div>
    )
}
