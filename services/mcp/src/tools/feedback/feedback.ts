import type { z } from 'zod'

import { AnalyticsEvent, buildMCPAnalyticsGroups, buildMCPContextProperties, getPostHogClient } from '@/lib/analytics'
import { FeedbackSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeedbackSchema

type Params = z.infer<typeof schema>

type Result = { content: Array<{ type: string; text: string }> }

export const feedbackHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const { feedback, category, severity, tool_name, skill_name } = params

    try {
        const distinctId = await context.getDistinctId()
        const analyticsContext = await context.stateManager.getAnalyticsContext().catch(() => ({}))

        const client = getPostHogClient()
        client.capture({
            distinctId,
            event: AnalyticsEvent.MCP_FEEDBACK_SUBMITTED,
            ...(Object.keys(buildMCPAnalyticsGroups(analyticsContext)).length > 0
                ? { groups: buildMCPAnalyticsGroups(analyticsContext) }
                : {}),
            properties: {
                feedback,
                ...(category ? { category } : {}),
                ...(severity ? { severity } : {}),
                ...(tool_name ? { tool_name } : {}),
                ...(skill_name ? { skill_name } : {}),
                ...buildMCPContextProperties(analyticsContext),
            },
        })
    } catch {
        // Never let analytics failures block feedback acknowledgement.
    }

    return {
        content: [
            {
                type: 'text',
                text: 'Thanks — your feedback was sent to the PostHog MCP team. We use this to make the MCP and PostHog skills better, so please keep it coming whenever something is confusing, broken, or missing.',
            },
        ],
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'feedback',
    schema,
    handler: feedbackHandler,
})

export default tool
