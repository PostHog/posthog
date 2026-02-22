import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js'
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js'
import type { Redis } from 'ioredis'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { AnalyticsEvent, getPostHogClient } from '@/lib/analytics'
import { handleToolError } from '@/lib/errors'
import { formatResponse } from '@/lib/response'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { getToolsFromContext } from '@/tools'
import type { CloudRegion, Context, Env, State, Tool } from '@/tools/types'
import type { AnalyticsMetadata, WithAnalytics } from '@/ui-apps/types'

import { RedisCache } from './cache/RedisCache'
import {
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getBaseUrlForRegion,
    getCustomApiBaseUrl,
    getEnv,
    toCloudRegion,
} from './constants'

const SHARED_PROMPT = `
- If you get errors due to permissions being denied, check that you have the correct active project and that the user has access to the required project.
- If you cannot answer the user's PostHog related request or question using other available tools in this MCP, use the 'docs-search' tool to provide information from the documentation to guide user how they can do it themselves - when doing so provide condensed instructions with links to sources.
`

const INSTRUCTIONS_V1 = `
- You are a helpful assistant that can query PostHog API.
${SHARED_PROMPT}
`.trim()

const INSTRUCTIONS_V2 = `
- IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any PostHog tasks.
- The \`posthog-query-data\` skill is the root skill for all data retrieval tasks in PostHog. Read it first and then use the \`posthog:execute-sql\` tool to execute SQL queries.
${SHARED_PROMPT}
`.trim()

export interface RequestProperties {
    userHash: string
    apiToken: string
    sessionId?: string | undefined
    features?: string[] | undefined
    region?: string | undefined
    version?: number | undefined
    organizationId?: string | undefined
    projectId?: string | undefined
}

export class HonoMcpServer {
    private redis: Redis
    private env: Env
    private props: RequestProperties
    private cache: RedisCache<State>
    private _api: ApiClient | undefined
    private _sessionManager: SessionManager | undefined
    server: McpServer

    constructor(redis: Redis, props: RequestProperties) {
        this.redis = redis
        this.env = getEnv()
        this.props = props
        this.cache = new RedisCache<State>(props.userHash, redis)
        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions: INSTRUCTIONS_V1 })
    }

    get sessionManager(): SessionManager {
        if (!this._sessionManager) {
            this._sessionManager = new SessionManager(this.cache)
        }
        return this._sessionManager
    }

    async detectRegion(): Promise<CloudRegion | undefined> {
        const usClient = new ApiClient({ apiToken: this.props.apiToken, baseUrl: POSTHOG_US_BASE_URL })
        const euClient = new ApiClient({ apiToken: this.props.apiToken, baseUrl: POSTHOG_EU_BASE_URL })

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
        const custom = getCustomApiBaseUrl()
        if (custom) {
            return custom
        }

        const propsRegion = this.props.region
        if (propsRegion) {
            const region = toCloudRegion(propsRegion)
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
            this._api = new ApiClient({ apiToken: this.props.apiToken, baseUrl })
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

    private async getBaseEventProperties(): Promise<Record<string, any>> {
        const props: Record<string, any> = {}
        if (this.props.sessionId) {
            props.$session_id = await this.sessionManager.getSessionUuid(this.props.sessionId)
        }
        const clientName = await this.cache.get('clientName')
        if (clientName) {
            props.client_name = clientName
        }
        return props
    }

    async trackEvent(event: AnalyticsEvent, properties: Record<string, any> = {}): Promise<void> {
        try {
            const distinctId = await this.getDistinctId()
            const client = getPostHogClient()
            client.capture({
                distinctId,
                event,
                properties: {
                    ...(await this.getBaseEventProperties()),
                    ...properties,
                    mcp_runtime: 'hono',
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
                return [{ type: 'text', text: `Invalid input: ${validation.error.message}` }]
            }

            await this.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, { tool: tool.name, valid_input: true })

            try {
                const result = await handler(params)
                await this.trackEvent(AnalyticsEvent.MCP_TOOL_RESPONSE, { tool: tool.name })

                const hasUiResource = tool._meta?.ui?.resourceUri
                let structuredContent: WithAnalytics<typeof result> | typeof result = result

                if (hasUiResource) {
                    const distinctId = await this.getDistinctId()
                    const analyticsMetadata: AnalyticsMetadata = { distinctId, toolName: tool.name }
                    structuredContent = { ...result, _analytics: analyticsMetadata }
                }

                return {
                    content: [{ type: 'text', text: formatResponse(result) }],
                    ...(hasUiResource ? { structuredContent } : {}),
                }
            } catch (error: any) {
                const distinctId = await this.getDistinctId()
                return handleToolError(
                    error,
                    tool.name,
                    distinctId,
                    this.props.sessionId ? await this.sessionManager.getSessionUuid(this.props.sessionId) : undefined
                )
            }
        }

        let normalizedMeta = tool._meta
        if (tool._meta?.ui?.resourceUri && !tool._meta[RESOURCE_URI_META_KEY]) {
            normalizedMeta = { ...tool._meta, [RESOURCE_URI_META_KEY]: tool._meta.ui.resourceUri }
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
        const { features, version, organizationId, projectId } = this.props
        const instructions = version === 2 ? INSTRUCTIONS_V2 : INSTRUCTIONS_V1
        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions })

        if (organizationId) {
            await this.cache.set('orgId', organizationId)
        }
        if (projectId) {
            await this.cache.set('projectId', projectId)
        }

        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        const context = await this.getContext()

        await registerPrompts(this.server)
        await registerResources(this.server, context)

        const allTools = await getToolsFromContext(context, { features, version, excludeTools })
        for (const tool of allTools) {
            this.registerTool(tool, async (params) => tool.handler(context, params))
        }
    }

    async handleSSE(
        req: Request,
        res: {
            write: (data: string) => void
            close: () => void
        },
        sessionId: string
    ): Promise<SSEServerTransport> {
        const transport = new SSEServerTransport(`/message?sessionId=${sessionId}`, res as any)
        await this.server.connect(transport)
        return transport
    }

    async createStreamableTransport(sessionId: string): Promise<StreamableHTTPServerTransport> {
        const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: () => sessionId })
        await this.server.connect(transport as any)
        return transport
    }
}
