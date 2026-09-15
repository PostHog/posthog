import { useActions, useValues } from 'kea'
import { SurveyQuestionType } from 'posthog-js'
import { useId } from 'react'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { MCPAnalyticsFeedbackPromptConfig, MCPFeedbackContext } from './constants'
import { mcpAnalyticsFeedbackLogic } from './mcpAnalyticsFeedbackLogic'
import { MCPFeedbackFollowUp } from './MCPFeedbackFollowUp'

const thumbRatings = [
    { value: '1', label: 'Thumbs up', icon: <IconThumbsUp /> },
    { value: '2', label: 'Thumbs down', icon: <IconThumbsDown /> },
]

export function MCPAnalyticsFeedbackPrompt({
    contextKey,
    context,
    prompt: promptConfig,
}: {
    contextKey: string
    context?: MCPFeedbackContext
    prompt: MCPAnalyticsFeedbackPromptConfig
}): JSX.Element | null {
    const questionId = useId()
    const { user } = useValues(userLogic)
    const logic = mcpAnalyticsFeedbackLogic({
        userId: user?.uuid ?? '',
        contextKey,
        context,
        prompt: promptConfig,
        isImpersonated: user?.is_impersonated ?? false,
    })
    const { visible, survey, prompt, answer, completed, submitting, error } = useValues(logic)
    const { dismissPrompt, submitResponse } = useActions(logic)

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
                    <MCPFeedbackFollowUp feedback={logic} />
                ) : (
                    <div className="space-y-2">
                        <div className="font-semibold" id={questionId}>
                            {prompt.question ?? survey.questions[0].question}
                        </div>
                        <div className="flex flex-wrap gap-2" role="group" aria-labelledby={questionId}>
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
