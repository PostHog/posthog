import { track } from '@posthog/mcp-analytics'
import type { JSONRPCRequest } from '@modelcontextprotocol/sdk/types.js'

import { getPostHogClient } from '@/lib/posthog'
import {
    AnalyticsEvent,
    buildEventProperties,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    type IdentityProvider,
    redactSensitiveInformation,
} from '@/lib/posthog/analytics'
import type { RequestProperties } from '@/lib/request-properties'
import { createExecInnerToolCallResolver } from '@/tools/exec'
import type { Env } from '@/tools/types'

import type { MethodHandlerCallbacks, ResolvedState } from './request-state-resolver'

interface AnalyticsAdapter {
    _requestHandlers: Map<string, (request: unknown, extra: unknown) => Promise<unknown>>
    setRequestHandler: (schema: { method: string }, handler: (request: unknown, extra: unknown) => Promise<unknown>) => void
    getClientVersion: () => string | undefined
    _serverInfo: { name: string; version: string }
    _capabilities: { tools: { listChanged: boolean } }
    [key: string | symbol]: unknown
}

export class AnalyticsBridge {
    private readonly _available: boolean

    constructor(env: Env) {
        this._available = !!(env.POSTHOG_ANALYTICS_API_KEY && env.POSTHOG_ANALYTICS_HOST)
    }

    get available(): boolean {
        return this._available
    }

    async dispatchThroughAnalytics(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState,
        handlers: MethodHandlerCallbacks
    ): Promise<unknown> {
        const adapter = this._createAdapter(props, state, handlers)

        try {
            const identity = this._buildIdentityProvider(state, props)

            const resolveExecInnerToolCall = state.useSingleExec
                ? createExecInnerToolCallResolver(state.allTools)
                : undefined
            const execInnerToolNames = state.useSingleExec
                ? state.allTools.map((t) => t.name)
                : undefined

            track(adapter as unknown as Parameters<typeof track>[0], {
                posthogClient: getPostHogClient(),
                context: true,
                enableAITracing: true,
                enableConversationId: false,
                enableTracing: true,
                identify: { userId: state.distinctId },
                reportMissing: !state.useSingleExec,
                eventTags: async () => {
                    const sessionUuid = await state.reqCtx.getSessionUuid(props.sessionId)
                    return sessionUuid
                        ? { $session_id: sessionUuid, $ai_session_id: sessionUuid }
                        : {}
                },
                eventProperties: async (req: unknown) => {
                    const base = await buildEventProperties(identity)
                    const innerToolCall = resolveExecInnerToolCall?.(req)
                    const isListToolsRequest =
                        (req as { method?: unknown })?.method === 'tools/list' &&
                        !!execInnerToolNames &&
                        execInnerToolNames.length > 0
                    return {
                        ...base,
                        ...(innerToolCall
                            ? {
                                  $mcp_exec_tool_call_name: innerToolCall.name,
                                  $mcp_exec_tool_call_description: innerToolCall.description,
                              }
                            : {}),
                        ...(isListToolsRequest
                            ? { $mcp_exec_inner_tool_names: [...(execInnerToolNames ?? [])] }
                            : {}),
                    }
                },
                redactSensitiveInformation: (text: string) =>
                    Promise.resolve(redactSensitiveInformation(text)),
            })
        } catch (e) {
            console.warn('[AnalyticsBridge] track() setup failed:', e)
        }

        const wrappedHandler = adapter._requestHandlers.get(request.method)
        if (!wrappedHandler) {
            throw new Error(`No handler for ${request.method}`)
        }

        const sdkRequest = { method: request.method, params: request.params ?? {} }
        const extra = { sessionId: props.mcpSessionId }
        return wrappedHandler(sdkRequest, extra)
    }

    async trackInitEvent(props: RequestProperties, state: ResolvedState): Promise<void> {
        try {
            const analyticsContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
            const initDurationMs = props.requestStartTime ? Date.now() - props.requestStartTime : undefined

            getPostHogClient().capture({
                distinctId: state.distinctId,
                event: AnalyticsEvent.MCP_INIT,
                properties: {
                    ...state.reqCtx.buildClientProperties(props),
                    tool_count: state.allTools.length,
                    has_organization_id: !!props.organizationId,
                    has_project_id: !!props.projectId,
                    read_only: !!props.readOnly,
                    via_sse_redirect: !!props.viaSseRedirect,
                    ...(props.mode ? { mcp_mode_explicit: props.mode } : {}),
                    ...(initDurationMs !== undefined ? { init_duration_ms: initDurationMs } : {}),
                    ...(props.sessionId
                        ? { $session_id: await state.reqCtx.getSessionUuid(props.sessionId) }
                        : {}),
                    ...(analyticsContext ? buildMCPContextProperties(analyticsContext) : {}),
                },
                ...(analyticsContext ? { groups: buildMCPAnalyticsGroups(analyticsContext) } : {}),
            })
        } catch {
            // skip
        }
    }

    private _createAdapter(
        props: RequestProperties,
        state: ResolvedState,
        handlers: MethodHandlerCallbacks
    ): AnalyticsAdapter {
        const adapter: AnalyticsAdapter = {
            _requestHandlers: new Map(),
            setRequestHandler(schema: { method: string }, handler: (req: unknown, extra: unknown) => Promise<unknown>) {
                adapter._requestHandlers.set(schema.method, handler)
            },
            getClientVersion: () => props.mcpProtocolVersion,
            _serverInfo: { name: 'PostHog', version: '1.0.0' },
            _capabilities: { tools: { listChanged: false } },
        }

        adapter._requestHandlers.set('initialize', async (req: unknown) => {
            const sdkParams = (req as { params?: Record<string, unknown> })?.params
            return handlers.handleInitialize(sdkParams, props, state)
        })
        adapter._requestHandlers.set('tools/list', async () => {
            return handlers.handleToolsList(state, props)
        })
        adapter._requestHandlers.set('tools/call', async (req: unknown) => {
            const sdkParams = (req as { params?: Record<string, unknown> })?.params
            return handlers.handleToolCall(sdkParams, props, state)
        })

        return adapter
    }

    private _buildIdentityProvider(state: ResolvedState, props: RequestProperties): IdentityProvider {
        return {
            getDistinctId: () => Promise.resolve(state.distinctId),
            getSessionUuid: () => state.reqCtx.getSessionUuid(props.sessionId),
            getMcpClientName: async () => props.mcpClientName,
            getMcpClientVersion: async () => props.mcpClientVersion,
            getMcpProtocolVersion: async () => props.mcpProtocolVersion,
            getRegion: async () => (await state.reqCtx.cache.get('region')) ?? props.region,
            getAnalyticsContext: async () => state.reqCtx.getAnalyticsContextSafe(state.context),
            getClientUserAgent: async () => props.clientUserAgent,
            getMcpVersion: async () => state.version,
            getOAuthClientName: async () => (await state.reqCtx.cache.get('clientName')) || undefined,
            getReadOnly: async () => props.readOnly,
            getTransport: async () => props.transport,
            getMcpConsumer: async () => props.mcpConsumer,
            getMcpMode: async () => (state.useSingleExec ? 'cli' : 'tools'),
            getMcpSessionId: async () => props.mcpSessionId,
            getMcpConversationId: async () => props.mcpConversationId,
        }
    }
}
