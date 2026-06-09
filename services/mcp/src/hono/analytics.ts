import { MCP_ANALYTICS_SOURCE, MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import { getPostHogClient } from '@/lib/posthog'
import {
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    MCP_ANALYTICS_VERSION,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'

import { buildMCPSessionAnalyticsProperties } from './mcp-context'
import type { ResolvedState } from './request-state-resolver'

function buildBaseProperties(
    state: ResolvedState,
    analyticsContext: MCPAnalyticsContext | undefined
): {
    properties: Record<string, unknown>
    groups: Record<string, string>
} {
    const groups = analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : {}
    const requestContext = state.requestContext

    const properties: Record<string, unknown> = {
        $ai_product: 'mcp',
        $mcp_source: MCP_ANALYTICS_SOURCE,
        $mcp_server_name: MCP_SERVER_NAME,
        $mcp_server_version: MCP_SERVER_VERSION,
        $mcp_version: MCP_ANALYTICS_VERSION,
        $mcp_client_name: requestContext.mcpClientName,
        $mcp_client_version: requestContext.mcpClientVersion,
        $mcp_client_user_agent: requestContext.clientUserAgent,
        $mcp_protocol_version: requestContext.mcpProtocolVersion,
        $mcp_transport: requestContext.transport,
        $mcp_session_id: requestContext.mcpSessionId,
        $mcp_conversation_id: requestContext.mcpConversationId,
        $mcp_consumer: requestContext.mcpConsumer,
        $mcp_mode: requestContext.mode,
        $mcp_region: requestContext.region,
        ...(analyticsContext
            ? {
                  $mcp_organization_id: analyticsContext.organizationId,
                  $mcp_project_id: analyticsContext.projectId,
                  $mcp_project_uuid: analyticsContext.projectUuid,
                  $mcp_project_name: analyticsContext.projectName,
                  ...buildMCPContextProperties(analyticsContext),
              }
            : {}),
        mcp_runtime: 'hono',
        mcp_vendor_client: requestContext.mcpVendorClient,
        ...buildMCPSessionAnalyticsProperties(state.sessionContext),
    }
    return { properties, groups }
}

export async function trackInitEvent(state: ResolvedState): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
        const requestContext = state.requestContext
        const initDurationMs = requestContext.requestStartTime
            ? Date.now() - requestContext.requestStartTime
            : undefined
        const sessionUuid = requestContext.sessionId
            ? await state.reqCtx.getSessionUuid(requestContext.sessionId)
            : undefined

        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        getPostHogClient().capture({
            distinctId: state.distinctId,
            event: 'mcp_initialize',
            ...(Object.keys(groups).length > 0 ? { groups } : {}),
            properties: {
                ...properties,
                $mcp_duration_ms: initDurationMs ?? 0,
                $mcp_is_error: false,
                tool_count: state.allTools.length,
                has_organization_id: !!requestContext.organizationId,
                has_project_id: !!requestContext.projectId,
                read_only: !!requestContext.readOnly,
                via_sse_redirect: !!requestContext.viaSseRedirect,
                ...(sessionUuid ? { $session_id: sessionUuid } : {}),
            },
        })
    } catch {
        // never break the request for analytics
    }
}

export async function trackToolCall(
    toolName: string,
    durationMs: number,
    isError: boolean,
    state: ResolvedState,
    extraProperties?: Record<string, unknown>
): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
        const requestContext = state.requestContext
        const sessionUuid = requestContext.sessionId
            ? await state.reqCtx.getSessionUuid(requestContext.sessionId)
            : undefined

        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        getPostHogClient().capture({
            distinctId: state.distinctId,
            event: 'mcp_tool_call',
            ...(Object.keys(groups).length > 0 ? { groups } : {}),
            properties: {
                ...properties,
                $mcp_tool_name: toolName,
                $mcp_duration_ms: durationMs,
                $mcp_is_error: isError,
                tool_name: toolName,
                ...(sessionUuid ? { $session_id: sessionUuid } : {}),
                ...extraProperties,
            },
        })
    } catch {
        // never break the request for analytics
    }
}
