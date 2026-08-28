import type { z } from 'zod'

import { getMoreToolsResult } from '@posthog/mcp-analytics'

import { AnalyticsEvent, MCP_ANALYTICS_VERSION } from '@/lib/posthog/analytics'
import { GetMoreToolsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

export const GET_MORE_TOOLS_TOOL_NAME = 'get-more-tools'

const schema = GetMoreToolsSchema

type Params = z.infer<typeof schema>
type Result = ReturnType<typeof getMoreToolsResult>

export const getMoreToolsHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    await context.trackEvent(AnalyticsEvent.MCP_MISSING_CAPABILITY, {
        $mcp_intent: params.missing_capability,
        $mcp_intent_source: 'context_parameter',
        $mcp_resource_name: GET_MORE_TOOLS_TOOL_NAME,
        $mcp_version: MCP_ANALYTICS_VERSION,
        missing_capability_goal: params.goal,
        missing_capability_blocked: params.blocked,
        ...(params.attempted_tool ? { missing_capability_attempted_tool: params.attempted_tool } : {}),
    })

    return getMoreToolsResult()
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: GET_MORE_TOOLS_TOOL_NAME,
    schema,
    handler: getMoreToolsHandler,
})

export default tool
