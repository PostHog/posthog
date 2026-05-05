import type { z } from 'zod'

import { AnalyticsEvent } from '@/lib/analytics'
import { FeedbackSubmitSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeedbackSubmitSchema

type Params = z.infer<typeof schema>

type Result = {
    received: boolean
    persisted: boolean
    summary: string
    sentiment: Params['sentiment']
    category: Params['category']
    message: string
}

const RESPONSE_MESSAGE =
    'Thank you for the feedback — it has been recorded and will be reviewed by the PostHog team. ' +
    "Submitting feedback does not mean your work is done: keep going and finish the user's task " +
    'using the other available tools.'

const CATEGORY_MAPPING: Record<Params['category'], string> = {
    tool_correctness: 'bug',
    tool_description: 'docs',
    tool_input_schema: 'usability',
    tool_output_format: 'usability',
    missing_tool: 'other',
    instructions_clarity: 'docs',
    performance: 'results',
    error_message: 'usability',
    other: 'other',
}

function buildFeedbackBody(params: Params): string {
    return [
        `Summary: ${params.summary}`,
        `Sentiment: ${params.sentiment}`,
        `Task completed: ${params.task_completed}`,
        params.tools_used?.length ? `Tools used: ${params.tools_used.join(', ')}` : undefined,
        params.friction_points ? `Friction points: ${params.friction_points}` : undefined,
        params.suggested_improvement ? `Suggested improvement: ${params.suggested_improvement}` : undefined,
        params.details ? `Details: ${params.details}` : undefined,
    ]
        .filter(Boolean)
        .join('\n')
}

async function persistFeedbackSubmission(context: Context, params: Params): Promise<boolean> {
    try {
        const projectId = await context.stateManager.getProjectId()
        const attemptedTool = params.tools_used?.at(-1) ?? ''
        await context.api.request({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(projectId)}/mcp_analytics/feedback/`,
            body: {
                goal: params.user_request ?? params.summary,
                feedback: buildFeedbackBody(params),
                category: CATEGORY_MAPPING[params.category],
                attempted_tool: attemptedTool,
                mcp_client_name: context.mcp?.clientName ?? '',
                mcp_client_version: context.mcp?.clientVersion ?? '',
                mcp_protocol_version: context.mcp?.protocolVersion ?? '',
                mcp_transport: context.mcp?.transport ?? '',
                mcp_session_id: context.mcp?.sessionUuid ?? '',
            },
        })
        return true
    } catch {
        return false
    }
}

export const submitFeedbackHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const persisted = await persistFeedbackSubmission(context, params)

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
            feedback_persisted: persisted,
            feedback_mcp_session_id: context.mcp?.sessionUuid,
            feedback_mcp_client_name: context.mcp?.clientName,
        })
    } catch {
        // Analytics is non-fatal — never surface as a tool failure.
    }

    return {
        received: true,
        persisted,
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
