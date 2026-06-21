import type { z } from 'zod'

import { AnalyticsEvent } from '@/lib/posthog/analytics'
import { PostHogFeedbackSubmitSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = PostHogFeedbackSubmitSchema

type Params = z.infer<typeof schema>

type Result = {
    received: boolean
    summary: string
    feedback_type: Params['feedback_type']
    sentiment: Params['sentiment']
    message: string
}

const RESPONSE_MESSAGE =
    'Thank you for the feedback — it has been recorded and will be reviewed by the PostHog team. ' +
    "Submitting feedback does not mean your work is done: keep going and finish the user's task " +
    'using the other available tools.'

export const submitPostHogFeedbackHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    // `context.trackEvent` is itself best-effort (the MCP-class implementation wraps
    // analytics in its own try/catch). The outer try/catch here defends against any
    // unexpected throw on the way *to* trackEvent so the agent never sees this tool
    // fail because of an analytics issue.
    try {
        await context.trackEvent(AnalyticsEvent.POSTHOG_FEEDBACK_SUBMITTED, {
            feedback_summary: params.summary,
            feedback_type: params.feedback_type,
            feedback_sentiment: params.sentiment,
            feedback_product_area: params.product_area,
            feedback_details: params.details,
            feedback_suggested_improvement: params.suggested_improvement,
            feedback_user_request: params.user_request,
            feedback_task_completed: params.task_completed,
        })
    } catch {
        // Analytics is non-fatal — never surface as a tool failure.
    }

    return {
        received: true,
        summary: params.summary,
        feedback_type: params.feedback_type,
        sentiment: params.sentiment,
        message: RESPONSE_MESSAGE,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'posthog-feedback',
    schema,
    handler: submitPostHogFeedbackHandler,
})

export default tool
