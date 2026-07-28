import { randomUUID } from 'node:crypto'

import type { MCPAnalyticsIntentSource } from '@posthog/mcp-analytics'

import { MCP_ANALYTICS_SOURCE, MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import { getPostHogClient } from '@/lib/posthog'
import {
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    MCP_ANALYTICS_VERSION,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
import { EXECUTE_SQL_TOOL_NAME } from '@/tools/posthogAiTools/executeSql'
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

        // The producer stamps the tool's category so the dashboard groups by it verbatim
        // (it never maps tool→category itself). Omitted when unknown (e.g. the `exec`
        // wrapper), which the dashboard buckets as "Uncategorized".
        const toolCategory = getToolCategory(toolName)

        // Emits `$mcp_tool_call` (+ `$mcp_is_error`). The SDK maps `toolName` →
        // `$mcp_tool_name`, `durationMs` → `$mcp_duration_ms`, `isError` →
        // `$mcp_is_error`, `intent` → `$mcp_intent`, and `sessionId` →
        // `$session_id`. `$exception` fan-out is disabled on the client, so an
        // errored call stays a single event.
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
    } catch {
        // never break the request for analytics
    }
}

export interface ExecuteSqlGenerationMeta {
    durationMs: number
    isError: boolean
    errorMessage?: string
}

/**
 * Manually captures an `$ai_generation` per `execute-sql` call — the client's LLM
 * authored the query; this server is the observer that sees intent and output
 * together. Lands in LLM analytics, where online evaluations (LLM judge / Hog) can
 * score it for anti-patterns on live traffic. `$ai_trace_id` is the MCP session
 * uuid, so a session's queries group into one trace.
 */
export async function trackExecuteSqlGeneration(
    toolName: string,
    args: unknown,
    state: ResolvedState,
    meta: ExecuteSqlGenerationMeta,
    intentMeta?: ToolCallIntentMeta
): Promise<void> {
    if (toolName !== EXECUTE_SQL_TOOL_NAME) {
        return
    }
    const query = (args as { query?: unknown } | null | undefined)?.query
    if (typeof query !== 'string' || query.length === 0) {
        return
    }
    try {
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(state.requestContext)
        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        getPostHogClient().capture({
            distinctId: state.distinctId,
            event: '$ai_generation',
            groups,
            properties: {
                ...properties,
                ...(sessionUuid ? { $session_id: sessionUuid } : {}),
                $ai_trace_id: sessionUuid ?? randomUUID(),
                $ai_span_name: EXECUTE_SQL_TOOL_NAME,
                $ai_input: [{ role: 'user', content: intentMeta?.intent ?? '' }],
                $ai_output_choices: [{ role: 'assistant', content: query }],
                $ai_latency: meta.durationMs / 1000,
                $ai_is_error: meta.isError,
                ...(meta.errorMessage ? { $ai_error: meta.errorMessage } : {}),
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

        // The SDK maps `toolNames` → `$mcp_listed_tool_names`, which powers
        // "advertised but never called" analysis.
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
