import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import { McpAgent } from 'agents/mcp'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { getPostHogClient } from '@/integrations/mcp/utils/client'
import { handleToolError } from '@/integrations/mcp/utils/handleToolError'
import type { AnalyticsEvent } from '@/lib/analytics'
import { CUSTOM_BASE_URL, MCP_DOCS_URL } from '@/lib/constants'
import { SessionManager } from '@/lib/utils/SessionManager'
import { StateManager } from '@/lib/utils/StateManager'
import { DurableObjectCache } from '@/lib/utils/cache/DurableObjectCache'
import { hash } from '@/lib/utils/helper-functions'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { getToolsFromContext } from '@/tools'
import type { CloudRegion, Context, State, Tool } from '@/tools/types'

const INSTRUCTIONS = `
- You are a helpful assistant that can query PostHog API.
- If you get errors due to permissions being denied, check that you have the correct active project and that the user has access to the required project.
- If you cannot answer the user's PostHog related request or question using other available tools in this MCP, use the 'docs-search' tool to provide information from the documentation to guide user how they can do it themselves - when doing so provide condensed instructions with links to sources.
`

type RequestProperties = {
    userHash: string
    apiToken: string
    sessionId?: string
    features?: string[]
}

// Define our MCP agent with tools
export class MyMCP extends McpAgent<Env> {
    server = new McpServer({
        name: 'PostHog',
        version: '1.0.0',
        instructions: INSTRUCTIONS,
    })

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

    get requestProperties() {
        return this.props as RequestProperties
    }

    get cache() {
        if (!this.requestProperties.userHash) {
            throw new Error('User hash is required to use the cache')
        }

        if (!this._cache) {
            this._cache = new DurableObjectCache<State>(
                this.requestProperties.userHash,
                this.ctx.storage
            )
        }

        return this._cache
    }

    get sessionManager() {
        if (!this._sessionManager) {
            this._sessionManager = new SessionManager(this.cache)
        }

        return this._sessionManager
    }

    async detectRegion(): Promise<CloudRegion | undefined> {
        const usClient = new ApiClient({
            apiToken: this.requestProperties.apiToken,
            baseUrl: 'https://us.posthog.com',
        })

        const euClient = new ApiClient({
            apiToken: this.requestProperties.apiToken,
            baseUrl: 'https://eu.posthog.com',
        })

        const [usResult, euResult] = await Promise.all([
            usClient.users().me(),
            euClient.users().me(),
        ])

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

    async getBaseUrl() {
        if (CUSTOM_BASE_URL) {
            return CUSTOM_BASE_URL
        }

        const region = (await this.cache.get('region')) || (await this.detectRegion())

        if (region === 'eu') {
            return 'https://eu.posthog.com'
        }

        return 'https://us.posthog.com'
    }

    async api() {
        if (!this._api) {
            const baseUrl = await this.getBaseUrl()
            this._api = new ApiClient({
                apiToken: this.requestProperties.apiToken,
                baseUrl,
            })
        }

        return this._api
    }

    async getDistinctId() {
        let _distinctId = await this.cache.get('distinctId')

        if (!_distinctId) {
            const userResult = await (await this.api()).users().me()
            if (!userResult.success) {
                throw new Error(`Failed to get user: ${userResult.error.message}`)
            }
            await this.cache.set('distinctId', userResult.data.distinct_id)
            _distinctId = userResult.data.distinct_id
        }

        return _distinctId
    }

    async trackEvent(event: AnalyticsEvent, properties: Record<string, any> = {}) {
        try {
            const distinctId = await this.getDistinctId()

            const client = getPostHogClient()

            client.capture({
                distinctId,
                event,
                properties: {
                    ...(this.requestProperties.sessionId
                        ? {
                              $session_id: await this.sessionManager.getSessionUuid(
                                  this.requestProperties.sessionId
                              ),
                          }
                        : {}),
                    ...properties,
                },
            })
        } catch (error) {
            //
        }
    }

    registerTool<TSchema extends z.ZodRawShape>(
        tool: Tool<z.ZodObject<TSchema>>,
        handler: (params: z.infer<z.ZodObject<TSchema>>) => Promise<any>
    ): void {
        const wrappedHandler = async (params: z.infer<z.ZodObject<TSchema>>) => {
            const validation = tool.schema.safeParse(params)

            if (!validation.success) {
                await this.trackEvent('mcp tool call', {
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

            await this.trackEvent('mcp tool call', {
                tool: tool.name,
                valid_input: true,
                input: params,
            })

            try {
                const result = await handler(params)
                await this.trackEvent('mcp tool response', {
                    tool: tool.name,
                    valid_input: true,
                    input: params,
                    output: result,
                })
                return result
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

    async init() {
        const context = await this.getContext()

        // Register prompts and resources
        await registerPrompts(this.server, context)
        registerResources(this.server, context)

        // Register tools
        const features = this.requestProperties.features
        const allTools = await getToolsFromContext(context, features)

        for (const tool of allTools) {
            this.registerTool(tool, async (params) => tool.handler(context, params))
        }
    }
}

export default {
    async fetch(request: Request, env: Env, ctx: ExecutionContext) {
        const url = new URL(request.url)

        if (url.pathname === '/') {
            return new Response(
                `<p>Welcome to the PostHog MCP Server. For setup and usage instructions, see: <a href="${MCP_DOCS_URL}">${MCP_DOCS_URL}</a></p>`,
                {
                    headers: {
                        'content-type': 'text/html',
                    },
                }
            )
        }

        const token = request.headers.get('Authorization')?.split(' ')[1]

        const sessionId = url.searchParams.get('sessionId')

        if (!token) {
            return new Response(
                `No token provided, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
                {
                    status: 401,
                }
            )
        }

        if (!token.startsWith('phx_') && !token.startsWith('pha_')) {
            return new Response(
                `Invalid token, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
                {
                    status: 401,
                }
            )
        }

        ctx.props = {
            apiToken: token,
            userHash: hash(token),
            sessionId: sessionId || undefined,
        }

        // Search params are used to build up the list of available tools. If no features are provided, all tools are available.
        // If features are provided, only tools matching those features will be available.
        // Features are provided as a comma-separated list in the "features" query parameter.
        // Example: ?features=org,insights
        const featuresParam = url.searchParams.get('features')
        const features = featuresParam ? featuresParam.split(',').filter(Boolean) : undefined
        ctx.props = { ...ctx.props, features }

        if (url.pathname.startsWith('/mcp')) {
            return MyMCP.serve('/mcp').fetch(request, env, ctx)
        }

        if (url.pathname.startsWith('/sse')) {
            return MyMCP.serveSSE('/sse').fetch(request, env, ctx)
        }

        return new Response('Not found', { status: 404 })
    },
}
