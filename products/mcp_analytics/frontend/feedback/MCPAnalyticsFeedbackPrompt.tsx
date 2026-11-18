import { useActions, useValues } from 'kea'
import { useEffect, useId } from 'react'
import { useInView } from 'react-intersection-observer'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { userLogic } from 'scenes/userLogic'

import { MCPAnalyticsFeedbackPromptConfig, MCP_ANALYTICS_FEEDBACK_RATINGS } from './constants'
import { mcpAnalyticsFeedbackLogic } from './mcpAnalyticsFeedbackLogic'

const thumbRatings = [
    { value: MCP_ANALYTICS_FEEDBACK_RATINGS.UP, label: 'Thumbs up', icon: <IconThumbsUp /> },
    { value: MCP_ANALYTICS_FEEDBACK_RATINGS.DOWN, label: 'Thumbs down', icon: <IconThumbsDown /> },
]

export function MCPAnalyticsFeedbackPrompt({
    contextKey,
    prompt: promptConfig,
    eligible = true,
}: {
    contextKey: string
    prompt: MCPAnalyticsFeedbackPromptConfig
    eligible?: boolean
}): JSX.Element | null {
    const questionId = useId()
    const detailId = useId()
    const { user } = useValues(userLogic)
    const logic = mcpAnalyticsFeedbackLogic({
        userId: user?.uuid ?? '',
        contextKey,
        eligible,
        prompt: promptConfig,
        isImpersonated: user?.is_impersonated ?? false,
    })
    const { visible, survey, prompt, answer, detail, completed, submitting, error } = useValues(logic)
    const { dismissPrompt, recordImpression, setDetail, submitResponse } = useActions(logic)
    const { ref, inView } = useInView({ threshold: 0.5, skip: !visible })
    const { isVisible: pageVisible } = usePageVisibility()

    useEffect(() => {
        if (visible && inView && pageVisible) {
            recordImpression()
        }
    }, [visible, inView, pageVisible, recordImpression])

    if (!visible || !survey) {
        return null
    }

    return (
        <div ref={ref} className="shrink-0 p-2" data-attr="mcp-analytics-feedback-prompt">
            <LemonBanner type="info" hideIcon onClose={dismissPrompt}>
                {completed ? (
                    <div role="status">Thanks for your feedback.</div>
                ) : answer ? (
                    <div className="space-y-2">
                        <div className="text-secondary text-xs" role="status">
                            Thanks for answering.
                        </div>
                        <LemonLabel htmlFor={detailId} showOptional>
                            {prompt.followUpQuestion}
                        </LemonLabel>
                        <LemonTextArea
                            id={detailId}
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
                        <div className="font-semibold" id={questionId}>
                            {prompt.question}
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
                                    data-feedback-rating={rating.value}
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
