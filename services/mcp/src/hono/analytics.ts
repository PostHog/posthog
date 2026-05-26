import { MCP_ANALYTICS_SOURCE, MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import { getPostHogClient } from '@/lib/posthog'
import { buildMCPAnalyticsGroups, buildMCPContextProperties, type MCPAnalyticsContext } from '@/lib/posthog/analytics'
import type { RequestProperties } from '@/lib/request-properties'

import type { ResolvedState } from './request-state-resolver'

function buildBaseProperties(
    state: ResolvedState,
    props: RequestProperties,
    analyticsContext: MCPAnalyticsContext | undefined
): {
    properties: Record<string, unknown>
    groups: Record<string, string>
} {
    const groups = analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : {}

    const properties: Record<string, unknown> = {
        $ai_product: 'mcp',
        $mcp_source: MCP_ANALYTICS_SOURCE,
        $mcp_server_name: MCP_SERVER_NAME,
        $mcp_server_version: MCP_SERVER_VERSION,
        $mcp_version: state.version,
        $mcp_client_name: props.mcpClientName,
        $mcp_client_version: props.mcpClientVersion,
        $mcp_client_user_agent: props.clientUserAgent,
        $mcp_protocol_version: props.mcpProtocolVersion,
        $mcp_transport: props.transport,
        $mcp_session_id: props.mcpSessionId,
        $mcp_conversation_id: props.mcpConversationId,
        $mcp_consumer: props.mcpConsumer,
        $mcp_mode: props.mode,
        $mcp_region: props.region,
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
    }
    return { properties, groups }
}

export async function trackInitEvent(props: RequestProperties, state: ResolvedState): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
        const initDurationMs = props.requestStartTime ? Date.now() - props.requestStartTime : undefined
        const sessionUuid = props.sessionId ? await state.reqCtx.getSessionUuid(props.sessionId) : undefined

        const { properties, groups } = buildBaseProperties(state, props, analyticsContext)

        getPostHogClient().capture({
            distinctId: state.distinctId,
            event: 'mcp_initialize',
            ...(Object.keys(groups).length > 0 ? { groups } : {}),
            properties: {
                ...properties,
                $mcp_duration_ms: initDurationMs ?? 0,
                $mcp_is_error: false,
                tool_count: state.allTools.length,
                has_organization_id: !!props.organizationId,
                has_project_id: !!props.projectId,
                read_only: !!props.readOnly,
                via_sse_redirect: !!props.viaSseRedirect,
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
    props: RequestProperties,
    state: ResolvedState,
    extraProperties?: Record<string, unknown>
): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
        const sessionUuid = props.sessionId ? await state.reqCtx.getSessionUuid(props.sessionId) : undefined

        const { properties, groups } = buildBaseProperties(state, props, analyticsContext)

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
