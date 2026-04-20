import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { z } from 'zod'

import { ApiClient, type GroupType } from '@/api/client'
import { AnalyticsEvent, getPostHogClient, isFeatureFlagEnabled } from '@/lib/analytics'
import { handleToolError } from '@/lib/errors'
import { buildInstructionsV2 } from '@/lib/instructions'
import { formatResponse } from '@/lib/response'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { registerUiAppResources } from '@/resources/ui-apps'
import INSTRUCTIONS_TEMPLATE_V1 from '@/templates/instructions-v1.md'
import INSTRUCTIONS_TEMPLATE_V2 from '@/templates/instructions-v2.md'
import {
    POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY,
    POSTHOG_META_KEY,
    type CloudRegion,
    type Context,
    type Env,
    type State,
    type Tool,
} from '@/tools/types'
import type { AnalyticsMetadata, WithAnalytics } from '@/ui-apps/types'

import { RedisCache, type RedisLike } from './cache/RedisCache'
import {
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getBaseUrlForRegion,
    getCustomApiBaseUrl,
    getEnv,
    toCloudRegion,
} from './constants'

let _guidelines = ''
try {
    // @ts-expect-error @shared/guidelines.md may not exist in all build environments
    const mod = require('@shared/guidelines.md')
    _guidelines = typeof mod === 'string' ? mod : (mod?.default ?? '')
} catch {
    _guidelines = ''
}

function buildInstructions(groupTypes?: GroupType[]): string {
    return buildInstructionsV2(INSTRUCTIONS_TEMPLATE_V2, _guidelines, groupTypes)
}

export interface RequestProperties {
    userHash: string
    apiToken: string
    sessionId?: string | undefined
    features?: string[] | undefined
    tools?: string[] | undefined
    region?: string | undefined
    version?: number | undefined
    organizationId?: string | undefined
    projectId?: string | undefined
    clientUserAgent?: string | undefined
    readOnly?: boolean | undefined
    transport?: 'streamable-http' | 'sse' | undefined
    requestStartTime?: number | undefined
}

export class HonoMcpServer {
    private env: Env
    private props: RequestProperties
    private cache: RedisCache<State>
    private _api: ApiClient | undefined
    private _sessionManager: SessionManager | undefined
    server: McpServer

    constructor(redis: RedisLike, props: RequestProperties) {
        this.env = getEnv()
        this.props = props
        this.cache = new RedisCache<State>(props.userHash, redis)
        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions: INSTRUCTIONS_TEMPLATE_V1 })
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
            this._api = new ApiClient({
                apiToken: this.props.apiToken,
                baseUrl,
                clientUserAgent: this.props.clientUserAgent,
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
            const clientName = await this.cache.get('clientName')

            client.capture({
                distinctId,
                event,
                properties: {
                    ...(this.props.sessionId
                        ? { $session_id: await this.sessionManager.getSessionUuid(this.props.sessionId) }
                        : {}),
                    ...(clientName ? { mcp_oauth_client_name: clientName } : {}),
                    ...(this.props.transport ? { mcp_transport: this.props.transport } : {}),
                    mcp_runtime: 'hono',
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
            const validation = tool.schema.safeParse(params)
            if (!validation.success) {
                return {
                    content: [{ type: 'text', text: `Invalid input: ${validation.error.message}` }],
                }
            }

            try {
                const { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: formattedResults, ...rawResult } =
                    await handler(params)

                const hasUiResource = tool._meta?.ui?.resourceUri
                let structuredContent: WithAnalytics<typeof rawResult> | typeof rawResult = rawResult

                if (hasUiResource) {
                    const distinctId = await this.getDistinctId()
                    const analyticsMetadata: AnalyticsMetadata = { distinctId, toolName: tool.name }
                    structuredContent = { ...rawResult, _analytics: analyticsMetadata }
                }

                const useJson = tool._meta?.[POSTHOG_META_KEY]?.responseFormat === 'json'
                const text = formattedResults ?? (useJson ? JSON.stringify(rawResult) : formatResponse(rawResult))

                return {
                    content: [{ type: 'text', text }],
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

    private async resolveVersionFlag(): Promise<number | undefined> {
        try {
            const distinctId = await this.getDistinctId()
            return (await isFeatureFlagEnabled('mcp-version-2', distinctId)) ? 2 : undefined
        } catch {
            return undefined
        }
    }

    private async getOrFetchGroupTypes(projectId: string): Promise<GroupType[] | undefined> {
        const GROUP_TYPES_TTL_MS = 5 * 60 * 1000
        try {
            const cached = await this.cache.get(`groupTypes:${projectId}`)
            const fetchedAt = await this.cache.get(`groupTypesFetchedAt:${projectId}`)
            const isStale = !fetchedAt || Date.now() - fetchedAt > GROUP_TYPES_TTL_MS
            if (cached !== undefined && !isStale) {
                return cached
            }
            return await this.fetchAndCacheGroupTypes(projectId)
        } catch {
            return undefined
        }
    }

    private async fetchAndCacheGroupTypes(projectId: string): Promise<GroupType[]> {
        const api = await this.api()
        const groupTypes = await api.getGroupTypes(projectId)
        await this.cache.set(`groupTypes:${projectId}`, groupTypes)
        await this.cache.set(`groupTypesFetchedAt:${projectId}`, Date.now())
        return groupTypes
    }

    async init(): Promise<void> {
        const { features, tools, version: clientVersion, organizationId, projectId, readOnly } = this.props

        const groupTypesPromise = projectId ? this.getOrFetchGroupTypes(projectId) : Promise.resolve(undefined)
        const flagPromise = this.resolveVersionFlag()

        if (organizationId) {
            await this.cache.set('orgId', organizationId)
        }
        if (projectId) {
            await this.cache.set('projectId', projectId)
        }

        const groupTypes = await groupTypesPromise
        const flagVersion = await flagPromise
        const version = flagVersion ?? clientVersion ?? 1
        const instructions = version === 2 ? buildInstructions(groupTypes) : INSTRUCTIONS_TEMPLATE_V1

        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions })

        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        const context = await this.getContext()

        await registerPrompts(this.server)
        await registerResources(this.server, context)
        await registerUiAppResources(this.server, context)

        const { getToolsFromContext } = await import('@/tools')
        const allTools = await getToolsFromContext(context, {
            features,
            tools,
            version,
            excludeTools,
            readOnly,
        })

        const oauthClientName = (await this.cache.get('clientName')) || undefined
        if (oauthClientName && this._api) {
            this._api.config.oauthClientName = oauthClientName
        }

        for (const tool of allTools) {
            const typedTool = tool as Tool<z.ZodObject>
            this.registerTool(typedTool, async (params) => typedTool.handler(context, params))
        }

        const initDurationMs = this.props.requestStartTime
            ? Date.now() - this.props.requestStartTime
            : undefined

        void this.trackEvent(AnalyticsEvent.MCP_INIT, {
            tool_count: allTools.length,
            mcp_version: version,
            has_organization_id: !!organizationId,
            has_project_id: !!projectId,
            read_only: !!readOnly,
            ...(initDurationMs !== undefined ? { init_duration_ms: initDurationMs } : {}),
        })
    }
}
