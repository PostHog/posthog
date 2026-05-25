import { getPostHogClient } from '@/lib/posthog'
import {
    AnalyticsEvent,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
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
    const properties: Record<string, unknown> = {
        mcp_runtime: 'hono',
        ...(props.mcpClientName ? { mcp_client_name: props.mcpClientName } : {}),
        ...(props.mcpClientVersion ? { mcp_client_version: props.mcpClientVersion } : {}),
        ...(props.mcpProtocolVersion ? { mcp_protocol_version: props.mcpProtocolVersion } : {}),
        ...(props.mcpConsumer ? { mcp_consumer: props.mcpConsumer } : {}),
        ...(props.transport ? { mcp_transport: props.transport } : {}),
        ...(props.mcpSessionId ? { mcp_session_id: props.mcpSessionId } : {}),
        ...(props.mcpConversationId ? { mcp_conversation_id: props.mcpConversationId } : {}),
        ...(props.mode ? { mcp_mode: props.mode } : {}),
        ...(analyticsContext ? buildMCPContextProperties(analyticsContext) : {}),
    }
    const groups = analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : {}
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
            event: AnalyticsEvent.MCP_INIT,
            ...(Object.keys(groups).length > 0 ? { groups } : {}),
            properties: {
                ...properties,
                tool_count: state.allTools.length,
                has_organization_id: !!props.organizationId,
                has_project_id: !!props.projectId,
                read_only: !!props.readOnly,
                via_sse_redirect: !!props.viaSseRedirect,
                ...(props.mode ? { mcp_mode_explicit: props.mode } : {}),
                ...(initDurationMs !== undefined ? { init_duration_ms: initDurationMs } : {}),
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
            event: AnalyticsEvent.MCP_TOOL_CALL,
            ...(Object.keys(groups).length > 0 ? { groups } : {}),
            properties: {
                ...properties,
                tool_name: toolName,
                $mcp_tool_name: toolName,
                $mcp_duration_ms: durationMs,
                $mcp_is_error: isError,
                ...(sessionUuid ? { $session_id: sessionUuid } : {}),
                ...extraProperties,
            },
        })
    } catch {
        // never break the request for analytics
    }
}
