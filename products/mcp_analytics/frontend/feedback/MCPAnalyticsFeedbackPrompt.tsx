import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FeedbackSurveyButton } from 'lib/components/FeedbackSurveyButton/FeedbackSurveyButton'
import { userLogic } from 'scenes/userLogic'

import { MCP_ANALYTICS_FEEDBACK_PROPERTIES, MCP_ANALYTICS_FEEDBACK_SURVEY_ID } from './constants'
import { mcpAnalyticsFeedbackLogic } from './mcpAnalyticsFeedbackLogic'

export function MCPAnalyticsFeedbackPrompt({ sessionId }: { sessionId: string }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const logic = mcpAnalyticsFeedbackLogic({
        userId: user?.uuid ?? '',
        sessionId,
        isImpersonated: user?.is_impersonated ?? false,
    })
    const { visible } = useValues(logic)
    const { dismissPrompt, openSurvey } = useActions(logic)

    if (!visible) {
        return null
    }

    return (
        <div className="shrink-0 p-2" data-attr="mcp-analytics-feedback-prompt">
            <LemonBanner type="info" hideIcon onClose={dismissPrompt}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <div className="flex-1 min-w-48">
                        <div className="font-semibold">What did you learn from these sessions?</div>
                        <div>Tell us what you changed or what was missing.</div>
                    </div>
                    <FeedbackSurveyButton
                        surveyId={MCP_ANALYTICS_FEEDBACK_SURVEY_ID}
                        properties={MCP_ANALYTICS_FEEDBACK_PROPERTIES}
                        onClick={openSurvey}
                        data-attr="mcp-analytics-contextual-feedback-button"
                    />
                </div>
            </LemonBanner>
        </div>
    )
}
