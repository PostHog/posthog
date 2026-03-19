import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import guidelines from '@shared/guidelines.md'
import { McpAgent } from 'agents/mcp'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { AnalyticsEvent, generateId, getPostHogClient } from '@/lib/analytics'
import { DurableObjectCache } from '@/lib/cache/DurableObjectCache'
import {
    CUSTOM_API_BASE_URL,
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getBaseUrlForRegion,
    toCloudRegion,
} from '@/lib/constants'
import { handleToolError } from '@/lib/errors'
import { formatResponse } from '@/lib/response'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { formatPrompt, sanitizeHeaderValue } from '@/lib/utils'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { registerUiAppResources } from '@/resources/ui-apps'
import INSTRUCTIONS_TEMPLATE_V1 from '@/templates/instructions-v1.md'
import INSTRUCTIONS_TEMPLATE_V2 from '@/templates/instructions-v2.md'
import type { CloudRegion, Context, State, Tool } from '@/tools/types'
import type { AnalyticsMetadata, WithAnalytics } from '@/ui-apps/types'

const INSTRUCTIONS_V2 = formatPrompt(INSTRUCTIONS_TEMPLATE_V2, {
    guidelines: guidelines.trim(),
})

export type RequestProperties = {
    userHash: string
    apiToken: string
    sessionId?: string
    features?: string[]
    region?: string
    version?: number
    organizationId?: string
    projectId?: string
    clientUserAgent?: string
    readOnly?: boolean
    transport?: 'streamable-http' | 'sse'
}

export class MCP extends McpAgent<Env> {
    server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions: INSTRUCTIONS_TEMPLATE_V1 })

    initialState: State = {
        projectId: undefined,
        orgId: undefined,
        distinctId: undefined,
        region: undefined,
        apiKey: undefined,
        clientName: undefined,
        aiConsentGiven: undefined,
        aiConsentFetchedAt: undefined,
    }

    _cache: DurableObjectCache<State> | undefined

    _api: ApiClient | undefined

    _sessionManager: SessionManager | undefined

    _clientInfoPromise: Promise<void> | undefined
    _mcpClientName: string | undefined
    _mcpClientVersion: string | undefined
    _mcpProtocolVersion: string | undefined

    get requestProperties(): RequestProperties {
        return this.props as RequestProperties
    }

    get cache(): DurableObjectCache<State> {
        if (!this.requestProperties.userHash) {
            throw new Error('User hash is required to use the cache')
        }

        if (!this._cache) {
            this._cache = new DurableObjectCache<State>(this.requestProperties.userHash, this.ctx.storage)
        }

        return this._cache
    }

    get sessionManager(): SessionManager {
        if (!this._sessionManager) {
            this._sessionManager = new SessionManager(this.cache)
        }

        return this._sessionManager
    }

    async resolveClientInfo(): Promise<void> {
        if (!this._clientInfoPromise) {
            this._clientInfoPromise = this._doResolveClientInfo()
        }
        return this._clientInfoPromise
    }

    private async _doResolveClientInfo(): Promise<void> {
        try {
            const initRequest = await this.getInitializeRequest()
            if (!initRequest || !('params' in initRequest)) {
                return
            }

            const params = (
                initRequest as {
                    params?: { clientInfo?: { name?: string; version?: string }; protocolVersion?: string }
                }
            ).params
            if (!params) {
                return
            }

            this._mcpClientName = sanitizeHeaderValue(params.clientInfo?.name)
            this._mcpClientVersion = sanitizeHeaderValue(params.clientInfo?.version)
            this._mcpProtocolVersion = sanitizeHeaderValue(params.protocolVersion)
        } catch {
            // skip
        }
    }

    async detectRegion(): Promise<CloudRegion | undefined> {
        const usClient = new ApiClient({
            apiToken: this.requestProperties.apiToken,
            baseUrl: POSTHOG_US_BASE_URL,
        })

        const euClient = new ApiClient({
            apiToken: this.requestProperties.apiToken,
            baseUrl: POSTHOG_EU_BASE_URL,
        })

        const [usResult, euResult] = await Promise.all([usClient.users().me(), euClient.users().me()])

        if (usResult.success) {
            await this.cache.set('region', 'us')
            return 'us'
        }

        if (euResult.success) {
            await this.cache.set('region', 'eu')
            return 'eu'
        }

        return undefined
    }

    async getBaseUrl(): Promise<string> {
        if (CUSTOM_API_BASE_URL) {
            return CUSTOM_API_BASE_URL
        }

        // Check region from request props first (passed via URL param), then cache, then detect
        const propsRegion = this.requestProperties.region
        if (propsRegion) {
            const region = toCloudRegion(propsRegion)
            // Cache it for future requests
            await this.cache.set('region', region)
            return getBaseUrlForRegion(region)
        }

        const cachedRegion = await this.cache.get('region')
        const region = cachedRegion ? toCloudRegion(cachedRegion) : await this.detectRegion()

        return getBaseUrlForRegion(region || 'us')
    }

    async api(): Promise<ApiClient> {
        if (!this._api) {
            const baseUrl = await this.getBaseUrl()
            await this.resolveClientInfo()
            this._api = new ApiClient({
                apiToken: this.requestProperties.apiToken,
                baseUrl,
                clientUserAgent: this.requestProperties.clientUserAgent,
                mcpClientName: this._mcpClientName,
                mcpClientVersion: this._mcpClientVersion,
                mcpProtocolVersion: this._mcpProtocolVersion,
            })
        }

        return this._api
    }

    async getDistinctId(): Promise<string> {
        let _distinctId = await this.cache.get('distinctId')

        if (!_distinctId) {
            const userResult = await (await this.api()).users().me()
            if (!userResult.success) {
                throw new Error(`Failed to get user: ${userResult.error.message}`)
            }
            await this.cache.set('distinctId', userResult.data.distinct_id)
            _distinctId = userResult.data.distinct_id as string
        }

        return _distinctId
    }

    async trackEvent(event: AnalyticsEvent, properties: Record<string, any> = {}): Promise<void> {
        try {
            const distinctId = await this.getDistinctId()

            const client = getPostHogClient(!!CUSTOM_API_BASE_URL)

            await this.resolveClientInfo()

            const clientName = await this.cache.get('clientName')

            client.capture({
                distinctId,
                event,
                properties: {
                    ...(this.requestProperties.sessionId
                        ? {
                              $session_id: await this.sessionManager.getSessionUuid(this.requestProperties.sessionId),
                          }
                        : {}),
                    ...(clientName ? { mcp_oauth_client_name: clientName } : {}),
                    ...(this._mcpClientName ? { mcp_client_name: this._mcpClientName } : {}),
                    ...(this._mcpClientVersion ? { mcp_client_version: this._mcpClientVersion } : {}),
                    ...(this._mcpProtocolVersion ? { mcp_protocol_version: this._mcpProtocolVersion } : {}),
                    ...(this.requestProperties.transport ? { mcp_transport: this.requestProperties.transport } : {}),
                    ...properties,
                },
            })
        } catch {
            // skip
        }
    }

    registerTool<TSchema extends z.ZodObject>(
        tool: Tool<TSchema>,
        handler: (params: z.infer<TSchema>) => Promise<any>
    ): void {
        const wrappedHandler = async (params: z.infer<TSchema>): Promise<any> => {
            const traceId = generateId()
            const spanId = generateId()
            const spanName = `mcp/${tool.name}`
            const startTime = performance.now()
            const inputState = params
            const validation = tool.schema.safeParse(params)

            if (!validation.success) {
                await this.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
                    tool: tool.name,
                    valid_input: false,
                    input: params,
                })
                const latency = (performance.now() - startTime) / 1000
                const errorOutput = `Invalid input: ${validation.error.message}`
                const outputState = { error: errorOutput }
                await this.trackEvent(AnalyticsEvent.AI_TRACE, {
                    $ai_trace_id: traceId,
                    $ai_span_name: spanName,
                    $ai_latency: latency,
                    $ai_is_error: true,
                    ai_product: 'mcp',
                })
                await this.trackEvent(AnalyticsEvent.AI_SPAN, {
                    $ai_trace_id: traceId,
                    $ai_span_id: spanId,
                    $ai_parent_id: traceId,
                    $ai_span_name: spanName,
                    $ai_input_state: inputState,
                    $ai_output_state: outputState,
                    $ai_latency: latency,
                    $ai_is_error: true,
                    ai_product: 'mcp',
                })
                return [
                    {
                        type: 'text',
                        text: errorOutput,
                    },
                ]
            }

            await this.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
                tool: tool.name,
                valid_input: true,
            })

            try {
                const result = await handler(params)
                const latency = (performance.now() - startTime) / 1000
                const outputState = result

                await this.trackEvent(AnalyticsEvent.MCP_TOOL_RESPONSE, {
                    tool: tool.name,
                })
                await this.trackEvent(AnalyticsEvent.AI_TRACE, {
                    $ai_trace_id: traceId,
                    $ai_span_name: spanName,
                    $ai_latency: latency,
                    ai_product: 'mcp',
                })
                await this.trackEvent(AnalyticsEvent.AI_SPAN, {
                    $ai_trace_id: traceId,
                    $ai_span_id: spanId,
                    $ai_parent_id: traceId,
                    $ai_span_name: spanName,
                    $ai_input_state: inputState,
                    $ai_output_state: outputState,
                    $ai_latency: latency,
                    ai_product: 'mcp',
                })

                // For tools with UI resources, include structuredContent for better UI rendering
                // structuredContent is not added to model context, only used by UI apps
                const hasUiResource = tool._meta?.ui?.resourceUri

                // If there's a UI resource, include analytics metadata for the UI app
                // The structuredContent is typed as WithAnalytics<T> where T is the tool result
                let structuredContent: WithAnalytics<typeof result> | typeof result = result
                if (hasUiResource) {
                    const distinctId = await this.getDistinctId()
                    const analyticsMetadata: AnalyticsMetadata = {
                        distinctId,
                        toolName: tool.name,
                    }
                    structuredContent = {
                        ...result,
                        _analytics: analyticsMetadata,
                    }
                }

                return {
                    content: [
                        {
                            type: 'text',
                            text: formatResponse(result),
                        },
                    ],
                    // Include raw result as structuredContent for UI apps to consume
                    ...(hasUiResource ? { structuredContent } : {}),
                }
            } catch (error: any) {
                const latency = (performance.now() - startTime) / 1000
                const errorMessage = error instanceof Error ? error.message : String(error)
                const outputState = { error: errorMessage }
                await this.trackEvent(AnalyticsEvent.AI_TRACE, {
                    $ai_trace_id: traceId,
                    $ai_span_name: spanName,
                    $ai_latency: latency,
                    $ai_is_error: true,
                    ai_product: 'mcp',
                })
                await this.trackEvent(AnalyticsEvent.AI_SPAN, {
                    $ai_trace_id: traceId,
                    $ai_span_id: spanId,
                    $ai_parent_id: traceId,
                    $ai_span_name: spanName,
                    $ai_input_state: inputState,
                    $ai_output_state: outputState,
                    $ai_latency: latency,
                    $ai_is_error: true,
                    ai_product: 'mcp',
                })
                const distinctId = await this.getDistinctId()
                return handleToolError(
                    error,
                    tool.name,
                    distinctId,
                    this.requestProperties.sessionId
                        ? await this.sessionManager.getSessionUuid(this.requestProperties.sessionId)
                        : undefined
                )
            }
        }

        // Normalize _meta to include both new (ui.resourceUri) and legacy (ui/resourceUri) formats
        // for compatibility with different MCP clients
        let normalizedMeta = tool._meta
        if (tool._meta?.ui?.resourceUri && !tool._meta[RESOURCE_URI_META_KEY]) {
            normalizedMeta = {
                ...tool._meta,
                [RESOURCE_URI_META_KEY]: tool._meta.ui.resourceUri,
            }
        }

        this.server.registerTool(
            tool.name,
            {
                title: tool.title,
                description: tool.description,
                inputSchema: tool.schema.shape,
                annotations: tool.annotations,
                ...(normalizedMeta ? { _meta: normalizedMeta } : {}),
            },
            wrappedHandler as unknown as ToolCallback<TSchema['shape']>
        )
    }

    async getContext(): Promise<Context> {
        const api = await this.api()
        return {
            api,
            cache: this.cache,
            env: this.env,
            stateManager: new StateManager(this.cache, api),
            sessionManager: this.sessionManager,
        }
    }

    async init(): Promise<void> {
        const { features, version, organizationId, projectId, readOnly } = this.requestProperties
        const instructions = version === 2 ? INSTRUCTIONS_V2 : INSTRUCTIONS_TEMPLATE_V1
        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions })

        // Pre-seed cache with org/project IDs from headers/query params
        if (organizationId) {
            await this.cache.set('orgId', organizationId)
        }
        if (projectId) {
            await this.cache.set('projectId', projectId)
        }

        // When project ID is provided, both switch tools are removed (project implies org).
        // When only organization ID is provided, only switch-organization is removed.
        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        const context = await this.getContext()

        // Register prompts and resources
        await registerPrompts(this.server)
        await registerResources(this.server, context)
        await registerUiAppResources(this.server, context)

        // Register tools
        const { getToolsFromContext } = await import('@/tools')
        const allTools = await getToolsFromContext(context, {
            features,
            version,
            excludeTools,
            readOnly,
        })

        // OAuth introspection has now run (triggered by getToolsFromContext → getApiKey),
        // so update the ApiClient with the verified OAuth client name for header forwarding.
        const oauthClientName = (await this.cache.get('clientName')) || undefined
        if (oauthClientName && this._api) {
            this._api.config.oauthClientName = oauthClientName
        }

        for (const tool of allTools) {
            const typedTool = tool as Tool<z.ZodObject>
            this.registerTool(typedTool, async (params) => typedTool.handler(context, params))
        }
    }
}
