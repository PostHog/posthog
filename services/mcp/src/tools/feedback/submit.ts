import type { z } from 'zod'

import { getPostHogClient } from '@/lib/analytics'
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

export const submitFeedbackHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const distinctId = await context.getDistinctId()
    const client = getPostHogClient()

    client.capture({
        distinctId,
        event: 'mcp feedback submitted',
        properties: {
            feedback_summary: params.summary,
            feedback_sentiment: params.sentiment,
            feedback_category: params.category,
            feedback_task_completed: params.task_completed,
            feedback_tools_used: params.tools_used,
            feedback_friction_points: params.friction_points,
            feedback_suggested_improvement: params.suggested_improvement,
            feedback_user_request: params.user_request,
            feedback_details: params.details,
        },
    })

    return {
        received: true,
        summary: params.summary,
        sentiment: params.sentiment,
        category: params.category,
        message:
            'Thank you for the feedback — it has been recorded and will be reviewed by the PostHog team. Continue helping the user with their task.',
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'feedback-submit',
    schema,
    handler: submitFeedbackHandler,
})

export default tool
