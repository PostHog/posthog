import type { MCPAnalyticsIntentSource } from '@posthog/mcp-analytics'

import { MCP_ANALYTICS_SOURCE, MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import { getPostHogClient } from '@/lib/posthog'
import {
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    MCP_ANALYTICS_VERSION,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
import { getToolCategory } from '@/tools/toolDefinitions'

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
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const requestContext = state.requestContext
        const initDurationMs = requestContext.requestStartTime
            ? Date.now() - requestContext.requestStartTime
            : undefined
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(requestContext)

        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        // Emits `$mcp_initialize`. The SDK maps `durationMs` → `$mcp_duration_ms`
        // and `sessionId` → `$session_id`; everything else rides on `properties`.
        getPostHogClient().captureInitialize({
            distinctId: state.distinctId,
            groups,
            durationMs: initDurationMs ?? 0,
            ...(sessionUuid ? { sessionId: sessionUuid } : {}),
            properties: {
                ...properties,
                $mcp_is_error: false,
                tool_count: state.allTools.length,
                has_organization_id: !!requestContext.organizationId,
                has_project_id: !!requestContext.projectId,
                read_only: !!requestContext.readOnly,
                via_sse_redirect: !!requestContext.viaSseRedirect,
            },
        })

        // TRANSITION SHIM — DELETE once the MCP insights + taxonomy are migrated to
        // the `$mcp_*` event names. `$mcp_initialize` (above) is the canonical event
        // going forward, but the existing dashboards/insights still key on the legacy
        // `mcp_initialize`, so we dual-emit it through the cutover to keep them working.
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

export interface ToolCallIntentMeta {
    /** The agent's stated intent (the injected `context` arg) → `$mcp_intent`. */
    intent?: string
    /** Where it came from → `$mcp_intent_source`. */
    intentSource?: MCPAnalyticsIntentSource
}

export async function trackToolCall(
    toolName: string,
    durationMs: number,
    isError: boolean,
    state: ResolvedState,
    extraProperties?: Record<string, unknown>,
    intentMeta?: ToolCallIntentMeta
): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const requestContext = state.requestContext
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(requestContext)

        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        // `$mcp_tool_category` is the dashboard's grouping dimension (e.g. "Logs",
        // "Tracing"). The contract is: the producer stamps the category onto every
        // tool-call event; the MCP analytics dashboard reads it back verbatim and
        // never maps tool names to categories itself. PostHog's server derives it
        // from its own catalog here; external servers using the SDK declare it per
        // tool. Omitted when unknown (e.g. the `exec` wrapper) so the dashboard
        // buckets those as "Uncategorized".
        const toolCategory = getToolCategory(toolName)

        // Emits `$mcp_tool_call` (+ `$mcp_is_error`). The SDK maps `toolName` →
        // `$mcp_tool_name`, `durationMs` → `$mcp_duration_ms`, `isError` →
        // `$mcp_is_error`, `intent` → `$mcp_intent`, and `sessionId` →
        // `$session_id`. `$exception` fan-out is disabled on the client, so an
        // errored call stays a single event. The intent pipeline reads
        // `$mcp_intent` off this canonical event, so it only needs to land here
        // (not on the legacy dual-emit below).
        getPostHogClient().captureToolCall({
            toolName,
            durationMs,
            isError,
            distinctId: state.distinctId,
            groups,
            ...(sessionUuid ? { sessionId: sessionUuid } : {}),
            ...(intentMeta?.intent ? { intent: intentMeta.intent } : {}),
            ...(intentMeta?.intentSource ? { intentSource: intentMeta.intentSource } : {}),
            properties: {
                ...properties,
                tool_name: toolName,
                ...(toolCategory ? { $mcp_tool_category: toolCategory } : {}),
                ...extraProperties,
            },
        })

        // TRANSITION SHIM — DELETE once the MCP insights + taxonomy are migrated to
        // the `$mcp_*` event names. `$mcp_tool_call` (above) is the canonical event
        // going forward, but the existing dashboards/insights still key on the legacy
        // `mcp_tool_call`, so we dual-emit it through the cutover to keep them working.
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
                ...(toolCategory ? { $mcp_tool_category: toolCategory } : {}),
                ...(sessionUuid ? { $session_id: sessionUuid } : {}),
                ...extraProperties,
            },
        })
    } catch {
        // never break the request for analytics
    }
}

export async function trackToolsList(toolNames: string[], state: ResolvedState): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const requestContext = state.requestContext
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(requestContext)

        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        // Emits `$mcp_tools_list`. The SDK maps `toolNames` → `$mcp_listed_tool_names`,
        // which powers "advertised but never called" analysis. No legacy dual-emit:
        // `mcp_tools_list` has had no consumers since the cutover.
        getPostHogClient().captureToolsList({
            toolNames,
            distinctId: state.distinctId,
            groups,
            ...(sessionUuid ? { sessionId: sessionUuid } : {}),
            properties: {
                ...properties,
                tool_count: toolNames.length,
            },
        })
    } catch {
        // never break the request for analytics
    }
}
