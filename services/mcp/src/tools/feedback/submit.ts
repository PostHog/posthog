import type { z } from 'zod'

import { AnalyticsEvent } from '@/lib/analytics'
import { FeedbackSubmitSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeedbackSubmitSchema

type Params = z.infer<typeof schema>

type Result = {
    received: boolean
    summary: string
    sentiment: Params['sentiment']
    category: Params['category']
    message: string
}

const RESPONSE_MESSAGE =
    'Thank you for the feedback — it has been recorded and will be reviewed by the PostHog team. ' +
    "Submitting feedback does not mean your work is done: keep going and finish the user's task " +
    'using the other available tools.'

export const submitFeedbackHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    // `context.trackEvent` is itself best-effort (the MCP-class implementation wraps
    // analytics in its own try/catch). The outer try/catch here defends against any
    // unexpected throw on the way *to* trackEvent (e.g. a future refactor) so the
    // agent never sees this tool fail because of an analytics issue.
    try {
        await context.trackEvent(AnalyticsEvent.MCP_FEEDBACK_SUBMITTED, {
            feedback_summary: params.summary,
            feedback_sentiment: params.sentiment,
            feedback_category: params.category,
            feedback_task_completed: params.task_completed,
            feedback_tools_used: params.tools_used,
            feedback_friction_points: params.friction_points,
            feedback_suggested_improvement: params.suggested_improvement,
            feedback_user_request: params.user_request,
            feedback_details: params.details,
        })
    } catch {
        // Analytics is non-fatal — never surface as a tool failure.
    }

    return {
        received: true,
        summary: params.summary,
        sentiment: params.sentiment,
        category: params.category,
        message: RESPONSE_MESSAGE,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'agent-feedback',
    schema,
    handler: submitFeedbackHandler,
})

export default tool
