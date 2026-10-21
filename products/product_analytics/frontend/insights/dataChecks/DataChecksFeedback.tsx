import { useActions, useValues } from 'kea'
import { useEffect, useId } from 'react'

import { IconThumbsDown, IconThumbsUp, IconX } from '@posthog/icons'
import { Button, Field, FieldLabel, Text, Textarea } from '@posthog/quill'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import {
    SURVEY_FEEDBACK_RATINGS,
    SurveyFeedbackPromptLogicProps,
    surveyFeedbackPromptLogic,
} from 'lib/logic/surveyFeedbackPrompt/surveyFeedbackPromptLogic'

const RATINGS = [
    { value: SURVEY_FEEDBACK_RATINGS.UP, label: 'Useful', icon: <IconThumbsUp /> },
    { value: SURVEY_FEEDBACK_RATINGS.DOWN, label: 'Not useful', icon: <IconThumbsDown /> },
]

export function DataChecksFeedback({ logicProps }: { logicProps: SurveyFeedbackPromptLogicProps }): JSX.Element | null {
    const questionId = useId()
    const detailId = useId()
    const logic = surveyFeedbackPromptLogic(logicProps)
    const { visible, survey, prompt, answer, detail, completed, submitting, error } = useValues(logic)
    const { dismissPrompt, recordImpression, setDetail, submitResponse } = useActions(logic)
    const { isVisible: pageVisible } = usePageVisibility()

    useEffect(() => {
        if (visible && pageVisible) {
            recordImpression()
        }
    }, [visible, pageVisible, recordImpression])

    if (!visible || !survey) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 border-t border-(--border) pt-2" data-attr="insight-data-checks-feedback">
            {completed ? (
                <Text size={null} variant="muted" role="status">
                    Thanks for your feedback.
                </Text>
            ) : answer ? (
                <>
                    <Field>
                        <FieldLabel htmlFor={detailId}>{prompt.followUpQuestion}</FieldLabel>
                        <Textarea
                            id={detailId}
                            value={detail}
                            onChange={(event) => setDetail(event.target.value)}
                            rows={2}
                            maxLength={2000}
                            autoFocus
                            disabled={submitting}
                            data-attr="insight-data-checks-feedback-detail"
                        />
                    </Field>
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        loading={submitting}
                        onClick={() => submitResponse(answer, true)}
                        data-attr="insight-data-checks-feedback-submit"
                    >
                        {detail.trim() ? 'Send feedback' : 'Done'}
                    </Button>
                </>
            ) : (
                <div className="flex items-center justify-between gap-2">
                    <Text id={questionId} size={null}>
                        {prompt.question}
                    </Text>
                    <div className="flex items-center gap-1">
                        <div className="flex items-center gap-1" role="group" aria-labelledby={questionId}>
                            {RATINGS.map((rating) => (
                                <Button
                                    key={rating.value}
                                    variant="outline"
                                    size="icon-sm"
                                    loading={submitting}
                                    aria-label={rating.label}
                                    tooltip={rating.label}
                                    onClick={() => submitResponse(rating.value, false)}
                                    data-attr="insight-data-checks-feedback-answer"
                                    data-feedback-rating={rating.value}
                                >
                                    {rating.icon}
                                </Button>
                            ))}
                        </div>
                        <Button
                            size="icon-sm"
                            aria-label="Dismiss"
                            tooltip="Dismiss"
                            onClick={dismissPrompt}
                            data-attr="insight-data-checks-feedback-dismiss"
                        >
                            <IconX />
                        </Button>
                    </div>
                </div>
            )}
            {error && (
                <Text size="xs" variant="destructive" role="alert">
                    Couldn't send your feedback. Please try again.
                </Text>
            )}
        </div>
    )
}
