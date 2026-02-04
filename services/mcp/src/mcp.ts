import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import { McpAgent } from 'agents/mcp'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { AnalyticsEvent, getPostHogClient } from '@/lib/analytics'
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
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { registerUiAppResources } from '@/resources/ui-apps'
import { getToolsFromContext } from '@/tools'
import type { CloudRegion, Context, State, Tool } from '@/tools/types'
import type { AnalyticsMetadata, WithAnalytics } from '@/ui-apps/types'

const INSTRUCTIONS = `
- You are a helpful assistant that can query PostHog API.
- If you get errors due to permissions being denied, check that you have the correct active project and that the user has access to the required project.
- If you cannot answer the user's PostHog related request or question using other available tools in this MCP, use the 'docs-search' tool to provide information from the documentation to guide user how they can do it themselves - when doing so provide condensed instructions with links to sources.
`

export type RequestProperties = {
    userHash: string
    apiToken: string
    sessionId?: string
    features?: string[]
    region?: string
}

export class MCP extends McpAgent<Env> {
    server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions: INSTRUCTIONS })

    initialState: State = {
        projectId: undefined,
        orgId: undefined,
        distinctId: undefined,
        region: undefined,
        apiKey: undefined,
    }

    _cache: DurableObjectCache<State> | undefined

    _api: ApiClient | undefined

    _sessionManager: SessionManager | undefined

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
            this._api = new ApiClient({
                apiToken: this.requestProperties.apiToken,
                baseUrl,
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

            const client = getPostHogClient()

            client.capture({
                distinctId,
                event,
                properties: {
                    ...(this.requestProperties.sessionId
                        ? {
                              $session_id: await this.sessionManager.getSessionUuid(this.requestProperties.sessionId),
                          }
                        : {}),
                    ...properties,
                },
            })
        } catch {
            // skip
        }
    }

    registerTool<TSchema extends z.ZodRawShape>(
        tool: Tool<z.ZodObject<TSchema>>,
        handler: (params: z.infer<z.ZodObject<TSchema>>) => Promise<any>
    ): void {
        const wrappedHandler = async (params: z.infer<z.ZodObject<TSchema>>): Promise<any> => {
            const validation = tool.schema.safeParse(params)

            if (!validation.success) {
                await this.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
                    tool: tool.name,
                    valid_input: false,
                    input: params,
                })
                return [
                    {
                        type: 'text',
                        text: `Invalid input: ${validation.error.message}`,
                    },
                ]
            }

            await this.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
                tool: tool.name,
                valid_input: true,
            })

            try {
                const result = await handler(params)
                await this.trackEvent(AnalyticsEvent.MCP_TOOL_RESPONSE, { tool: tool.name })

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
            wrappedHandler as unknown as ToolCallback<TSchema>
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
        const context = await this.getContext()

        // Register prompts and resources
        await registerPrompts(this.server)
        await registerResources(this.server, context)
        await registerUiAppResources(this.server, context)

        // Register tools
        const features = this.requestProperties.features
        const allTools = await getToolsFromContext(context, features)

        for (const tool of allTools) {
            this.registerTool(tool, async (params) => tool.handler(context, params))
        }
    }
}
