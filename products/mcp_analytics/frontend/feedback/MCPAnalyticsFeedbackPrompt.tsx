import { useActions, useValues } from 'kea'
import { SurveyQuestionType } from 'posthog-js'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { mcpAnalyticsFeedbackLogic } from './mcpAnalyticsFeedbackLogic'

const thumbRatings = [
    { value: '1', label: 'Thumbs up', icon: <IconThumbsUp /> },
    { value: '2', label: 'Thumbs down', icon: <IconThumbsDown /> },
]

export function MCPAnalyticsFeedbackPrompt({ sessionId }: { sessionId: string }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const logic = mcpAnalyticsFeedbackLogic({
        userId: user?.uuid ?? '',
        sessionId,
        isImpersonated: user?.is_impersonated ?? false,
    })
    const { visible, survey, answer, detail, completed, submitting, error } = useValues(logic)
    const { dismissPrompt, setDetail, submitResponse } = useActions(logic)

    if (
        !visible ||
        !survey ||
        survey.questions[0].type !== SurveyQuestionType.Rating ||
        survey.questions[0].scale !== 2
    ) {
        return null
    }

    return (
        <div className="shrink-0 p-2" data-attr="mcp-analytics-feedback-prompt">
            <LemonBanner type="info" hideIcon onClose={dismissPrompt}>
                {completed ? (
                    <div role="status">Thanks for your feedback.</div>
                ) : answer ? (
                    <div className="space-y-2">
                        <div className="text-secondary text-xs" role="status">
                            Thanks for answering.
                        </div>
                        <LemonLabel htmlFor="mcp-session-feedback-detail" showOptional>
                            {survey.questions[1].question}
                        </LemonLabel>
                        <LemonTextArea
                            id="mcp-session-feedback-detail"
                            value={detail}
                            onChange={setDetail}
                            autoFocus
                            minRows={2}
                            maxRows={4}
                            maxLength={2000}
                            disabled={submitting}
                            data-attr="mcp-analytics-feedback-detail"
                        />
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                loading={submitting}
                                onClick={() => submitResponse(answer, true)}
                                data-attr="mcp-analytics-feedback-submit"
                            >
                                {detail.trim() ? 'Send feedback' : 'Done'}
                            </LemonButton>
                        </div>
                    </div>
                ) : (
                    <div className="space-y-2">
                        <div className="font-semibold" id="mcp-session-feedback-question">
                            {survey.questions[0].question}
                        </div>
                        <div
                            className="flex flex-wrap gap-2"
                            role="group"
                            aria-labelledby="mcp-session-feedback-question"
                        >
                            {thumbRatings.map((rating) => (
                                <LemonButton
                                    key={rating.value}
                                    type="secondary"
                                    size="small"
                                    loading={submitting}
                                    icon={rating.icon}
                                    aria-label={rating.label}
                                    tooltip={rating.label}
                                    onClick={() => submitResponse(rating.value, false)}
                                    data-attr="mcp-analytics-feedback-answer"
                                />
                            ))}
                        </div>
                    </div>
                )}
                {error && (
                    <div className="text-danger mt-2" role="alert">
                        Couldn't send your feedback. Please try again.
                    </div>
                )}
            </LemonBanner>
        </div>
    )
}
