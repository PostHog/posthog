import { ApiClient } from '@/api/client'
import { MCPClientProfile } from '@/lib/client-detection'
import { wrapError } from '@/lib/errors'
import {
    AnalyticsEvent,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
import { getPostHogClient } from '@/lib/posthog'
import { evaluateFeatureFlags, isFeatureFlagEnabled } from '@/lib/posthog/flags'
import type { RequestProperties } from '@/lib/request-properties'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { getRequiredFeatureFlags } from '@/tools/toolDefinitions'
import type { Context, Env, State } from '@/tools/types'

import { RedisCache, type RedisLike } from '../cache/RedisCache'
import { getCustomApiBaseUrl } from '../constants'
import type { ToolCatalog } from '../tool-catalog'

import { type ResolvedState, resolveModeAndVersion } from './types'

export class RequestContext {
    private _cache: RedisCache<State> | undefined
    private _api: ApiClient | undefined
    private readonly redis: RedisLike
    private readonly env: Env
    private readonly props: RequestProperties

    constructor(redis: RedisLike, env: Env, props: RequestProperties) {
        this.redis = redis
        this.env = env
        this.props = props
    }

    get cache(): RedisCache<State> {
        if (!this.props.userHash) {
            throw new Error('User hash is required to use the cache')
        }
        if (!this._cache) {
            this._cache = new RedisCache<State>(this.props.userHash, this.redis)
        }
        return this._cache
    }

    private async api(): Promise<ApiClient> {
        if (!this._api) {
            const customApiBaseUrl = getCustomApiBaseUrl()
            let baseUrl: string
            if (customApiBaseUrl) {
                baseUrl = customApiBaseUrl
            } else if (process.env.NODE_ENV === 'production') {
                throw new Error(
                    'POSTHOG_API_BASE_URL must be set in production — Hono deployments are regional and do not auto-detect.'
                )
            } else {
                baseUrl = 'http://localhost:8010'
            }
            this._api = new ApiClient({
                apiToken: this.props.apiToken,
                baseUrl,
                clientUserAgent: this.props.clientUserAgent,
                mcpClientName: this.props.mcpClientName,
                mcpClientVersion: this.props.mcpClientVersion,
                mcpProtocolVersion: this.props.mcpProtocolVersion,
                mcpConsumer: this.props.mcpConsumer,
            })
        }
        return this._api
    }

    async getDistinctId(): Promise<string> {
        let distinctId = await this.cache.get('distinctId')
        if (!distinctId) {
            const userResult = await (await this.api()).users().me()
            if (!userResult.success) {
                throw wrapError(`Failed to get user: ${userResult.error.message}`, userResult.error)
            }
            await this.cache.set('distinctId', userResult.data.distinct_id)
            distinctId = userResult.data.distinct_id as string
        }
        return distinctId
    }

    async getContext(): Promise<Context> {
        const api = await this.api()
        const stateManager = new StateManager(this.cache, api)
        const partialContext: Omit<Context, 'trackEvent'> = {
            api,
            cache: this.cache,
            env: this.env,
            stateManager,
            sessionManager: new SessionManager(this.cache),
            getDistinctId: () => this.getDistinctId(),
        }
        const trackEvent: Context['trackEvent'] = async (event, properties = {}) => {
            const analyticsContext = await this.getAnalyticsContextSafe(partialContext)
            const distinctId = await this.getDistinctId()
            await this._trackEvent(event, properties, analyticsContext, undefined, distinctId, this.props)
        }
        return { ...partialContext, trackEvent }
    }

    async getAnalyticsContextSafe(
        context: Pick<Context, 'stateManager'>
    ): Promise<MCPAnalyticsContext | undefined> {
        try {
            return await context.stateManager.getAnalyticsContext()
        } catch {
            return undefined
        }
    }

    async trackContextSwitchEvent(
        toolName: string,
        context: Context,
        previousContext: MCPAnalyticsContext | undefined
    ): Promise<void> {
        const resolvedContext = await this.getAnalyticsContextSafe(context)
        if (!resolvedContext) return

        const event =
            toolName === 'switch-project'
                ? AnalyticsEvent.MCP_PROJECT_SWITCHED
                : toolName === 'switch-organization'
                  ? AnalyticsEvent.MCP_ORGANIZATION_SWITCHED
                  : undefined
        if (!event) return

        const distinctId = await this.getDistinctId()
        await this._trackEvent(event, {}, resolvedContext, previousContext, distinctId, this.props)
    }

    async resolveVersionFlag(): Promise<number | undefined> {
        try {
            const distinctId = await this.getDistinctId()
            return (await isFeatureFlagEnabled('mcp-version-2', distinctId)) ? 2 : undefined
        } catch {
            return undefined
        }
    }

    async resolveSingleExecFlag(): Promise<boolean> {
        try {
            const distinctId = await this.getDistinctId()
            return !!(await isFeatureFlagEnabled('mcp-single-exec-tool', distinctId))
        } catch {
            return false
        }
    }

    async resolveToolFeatureFlags(version?: number): Promise<Record<string, boolean> | undefined> {
        try {
            const flagKeys = getRequiredFeatureFlags(version)
            if (flagKeys.length === 0) return undefined
            const distinctId = await this.getDistinctId()
            return await evaluateFeatureFlags(flagKeys, distinctId)
        } catch {
            return undefined
        }
    }

    async _trackEvent(
        event: AnalyticsEvent,
        properties: Record<string, unknown>,
        analyticsContext?: MCPAnalyticsContext,
        previousContext?: MCPAnalyticsContext,
        distinctId?: string,
        props?: RequestProperties
    ): Promise<void> {
        try {
            const resolvedDistinctId = distinctId ?? (await this.getDistinctId())
            const resolvedProps = props ?? this.props
            const clientName = await this.cache.get('clientName')
            const contextProperties = analyticsContext ? buildMCPContextProperties(analyticsContext) : {}
            const previousContextProperties = previousContext
                ? buildMCPContextProperties(previousContext, { prefix: 'previous_' })
                : {}
            const groups = analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : {}

            getPostHogClient().capture({
                distinctId: resolvedDistinctId,
                event,
                ...(Object.keys(groups).length > 0 ? { groups } : {}),
                properties: {
                    mcp_runtime: 'hono',
                    ...(resolvedProps.sessionId
                        ? { $session_id: await new SessionManager(this.cache).getSessionUuid(resolvedProps.sessionId) }
                        : {}),
                    ...(clientName ? { mcp_oauth_client_name: clientName } : {}),
                    ...(resolvedProps.mcpClientName ? { mcp_client_name: resolvedProps.mcpClientName } : {}),
                    ...(resolvedProps.mcpClientVersion ? { mcp_client_version: resolvedProps.mcpClientVersion } : {}),
                    ...(resolvedProps.mcpProtocolVersion
                        ? { mcp_protocol_version: resolvedProps.mcpProtocolVersion }
                        : {}),
                    ...(resolvedProps.mcpConsumer ? { mcp_consumer: resolvedProps.mcpConsumer } : {}),
                    ...(resolvedProps.transport ? { mcp_transport: resolvedProps.transport } : {}),
                    ...contextProperties,
                    ...previousContextProperties,
                    ...properties,
                },
            })
        } catch {
            // skip
        }
    }
}

export class RequestStateResolver {
    private readonly catalog: ToolCatalog
    private readonly redis: RedisLike
    private readonly env: Env

    constructor(catalog: ToolCatalog, redis: RedisLike, env: Env) {
        this.catalog = catalog
        this.redis = redis
        this.env = env
    }

    async resolve(props: RequestProperties): Promise<ResolvedState> {
        const reqCtx = new RequestContext(this.redis, this.env, props)
        const context = await reqCtx.getContext()

        const { features, tools, version: clientVersion, organizationId, projectId, readOnly, mode } = props

        if (organizationId) await reqCtx.cache.set('orgId', organizationId)
        if (projectId) await reqCtx.cache.set('projectId', projectId)

        let cachedProjectId = projectId || (await reqCtx.cache.get('projectId'))
        if (!cachedProjectId) {
            await context.stateManager.setDefaultOrganizationAndProject()
            cachedProjectId = (await reqCtx.cache.get('projectId')) ?? undefined
        }

        const [flagVersion, toolFeatureFlags, singleExecFlagOn, _apiKey, distinctId] = await Promise.all([
            reqCtx.resolveVersionFlag(),
            reqCtx.resolveToolFeatureFlags(clientVersion),
            reqCtx.resolveSingleExecFlag(),
            context.stateManager.getApiKey(),
            reqCtx.getDistinctId(),
        ])

        const oauthClientName = (await reqCtx.cache.get('clientName')) || undefined
        const clientProfile = new MCPClientProfile({
            clientName: props.mcpClientName,
            clientVersion: props.mcpClientVersion,
            consumer: props.mcpConsumer,
            oauthClientName,
        })

        const { useSingleExec, version } = resolveModeAndVersion({
            mode,
            singleExecFlagOn,
            clientProfile,
            flagVersion,
            clientVersion,
        })

        const apiKeyScopes = _apiKey?.scopes ?? []
        const aiConsentGiven = await context.stateManager.getAiConsentGiven()

        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        const allTools = this.catalog.getFilteredTools({
            features,
            tools,
            version,
            excludeTools,
            readOnly,
            featureFlags: toolFeatureFlags,
            scopes: apiKeyScopes,
            aiConsentGiven: aiConsentGiven ?? undefined,
        })

        return {
            reqCtx,
            context,
            version,
            useSingleExec,
            toolFeatureFlags,
            apiKeyScopes,
            clientProfile,
            allTools,
            distinctId,
        }
    }
}
