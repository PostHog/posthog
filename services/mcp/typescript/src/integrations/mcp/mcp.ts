import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import { McpAgent } from 'agents/mcp'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { getPostHogClient } from '@/integrations/mcp/utils/client'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'
import { handleToolError } from '@/integrations/mcp/utils/handleToolError'
import { AnalyticsEvent } from '@/lib/analytics'
import {
    CUSTOM_BASE_URL,
    getBaseUrlForRegion,
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    toCloudRegion,
} from '@/lib/constants'
import { SessionManager } from '@/lib/utils/SessionManager'
import { StateManager } from '@/lib/utils/StateManager'
import { DurableObjectCache } from '@/lib/utils/cache/DurableObjectCache'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { getToolsFromContext } from '@/tools'
import type { CloudRegion, Context, State, Tool } from '@/tools/types'

const INSTRUCTIONS = `
- You are a helpful assistant that can query PostHog API.
- If you get errors due to permissions being denied, check that you have the correct active project and that the user has access to the required project.
- If you cannot answer the user's PostHog related request or question using other available tools in this MCP, use the 'docs-search' tool to provide information from the documentation to guide user how they can do it themselves - when doing so provide condensed instructions with links to sources.
`

export type RequestProperties = {
    /**
     * PBKDF2 hash of the API token, used to namespace per-user data in Durable Object storage.
     *
     * Durable Objects provide a single shared SQLite storage instance. To isolate users,
     * the DurableObjectCache prefixes all storage keys with `user:${userHash}:`. For example:
     *   - User A's region → `user:abc123:region`
     *   - User B's region → `user:def456:region`
     *
     * This ensures users can't access each other's cached data while sharing the same
     * Durable Object infrastructure.
     *
     * See: src/lib/utils/helper-functions.ts for the PBKDF2 hash implementation.
     */
    userHash: string
    apiToken: string
    sessionId?: string
    features?: string[]
    region?: string
}

export class MCP extends McpAgent<Env> {
    server = new McpServer(
        { name: 'PostHog', version: '1.0.0' },
        { instructions: INSTRUCTIONS }
    )

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

    /**
     * Per-user cache backed by Durable Object SQLite storage.
     *
     * Durable Objects provide a single shared storage instance (`this.ctx.storage`).
     * To isolate users, we pass `userHash` to DurableObjectCache, which prefixes
     * all keys with `user:${userHash}:`. For example:
     *
     *   cache.set('region', 'us')  →  storage.put('user:abc123:region', 'us')
     *
     * This ensures User A (hash abc123) and User B (hash def456) have completely
     * separate data within the same underlying storage.
     */
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
        if (CUSTOM_BASE_URL) {
            return CUSTOM_BASE_URL
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
                input: params,
            })

            try {
                const result = await handler(params)
                await this.trackEvent(AnalyticsEvent.MCP_TOOL_RESPONSE, {
                    tool: tool.name,
                    valid_input: true,
                    input: params,
                    output: result,
                })

                return {
                    content: [
                        {
                            type: 'text',
                            text: formatResponse(result),
                        },
                    ],
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

        this.server.registerTool(
            tool.name,
            {
                title: tool.title,
                description: tool.description,
                inputSchema: tool.schema.shape,
                annotations: tool.annotations,
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
        await registerPrompts(this.server, context)
        await registerResources(this.server, context)

        // Register tools
        const features = this.requestProperties.features
        const allTools = await getToolsFromContext(context, features)

        for (const tool of allTools) {
            this.registerTool(tool, async (params) => tool.handler(context, params))
        }
    }
}