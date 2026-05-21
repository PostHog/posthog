import { ApiClient } from '@/api/client'
import { wrapError } from '@/lib/errors'
import {
    AnalyticsEvent,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
import { getPostHogClient } from '@/lib/posthog'
import type { RequestProperties } from '@/lib/request-properties'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import type { Context, Env, State } from '@/tools/types'

import { RedisCache, type RedisLike } from './cache/RedisCache'
import { getCustomApiBaseUrl } from './constants'

export class RequestContext {
    private _cache: RedisCache<State> | undefined
    private _api: ApiClient | undefined
    private _sessionManager: SessionManager | undefined
    private _distinctIdPromise: Promise<string> | undefined
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

    get sessionManager(): SessionManager {
        if (!this._sessionManager) {
            this._sessionManager = new SessionManager(this.cache)
        }
        return this._sessionManager
    }

    async getSessionUuid(sessionId: string | undefined): Promise<string | undefined> {
        if (!sessionId) {return undefined}
        return this.sessionManager.getSessionUuid(sessionId)
    }

    getDistinctId(): Promise<string> {
        if (!this._distinctIdPromise) {
            this._distinctIdPromise = this._resolveDistinctId()
        }
        return this._distinctIdPromise
    }

    private async _resolveDistinctId(): Promise<string> {
        const cached = await this.cache.get('distinctId')
        if (cached) {return cached}
        const userResult = await (await this.api()).users().me()
        if (!userResult.success) {
            throw wrapError(`Failed to get user: ${userResult.error.message}`, userResult.error)
        }
        await this.cache.set('distinctId', userResult.data.distinct_id)
        return userResult.data.distinct_id as string
    }

    async getContext(): Promise<Context> {
        const api = await this.api()
        const stateManager = new StateManager(this.cache, api)
        const partialContext: Omit<Context, 'trackEvent'> = {
            api,
            cache: this.cache,
            env: this.env,
            stateManager,
            sessionManager: this.sessionManager,
            getDistinctId: () => this.getDistinctId(),
        }
        const trackEvent: Context['trackEvent'] = async (event, properties = {}) => {
            const analyticsContext = await this.getAnalyticsContextSafe(partialContext)
            const distinctId = await this.getDistinctId()
            await this.trackEvent(event, properties, analyticsContext, undefined, distinctId, this.props)
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
        if (!resolvedContext) {return}

        const event =
            toolName === 'switch-project'
                ? AnalyticsEvent.MCP_PROJECT_SWITCHED
                : toolName === 'switch-organization'
                  ? AnalyticsEvent.MCP_ORGANIZATION_SWITCHED
                  : undefined
        if (!event) {return}

        const distinctId = await this.getDistinctId()
        await this.trackEvent(event, {}, resolvedContext, previousContext, distinctId, this.props)
    }

    buildClientProperties(props?: RequestProperties): Record<string, unknown> {
        const p = props ?? this.props
        return {
            mcp_runtime: 'hono',
            ...(p.mcpClientName ? { mcp_client_name: p.mcpClientName } : {}),
            ...(p.mcpClientVersion ? { mcp_client_version: p.mcpClientVersion } : {}),
            ...(p.mcpProtocolVersion ? { mcp_protocol_version: p.mcpProtocolVersion } : {}),
            ...(p.mcpConsumer ? { mcp_consumer: p.mcpConsumer } : {}),
            ...(p.transport ? { mcp_transport: p.transport } : {}),
        }
    }

    async trackEvent(
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
                    ...this.buildClientProperties(resolvedProps),
                    ...(resolvedProps.sessionId
                        ? { $session_id: await this.getSessionUuid(resolvedProps.sessionId) }
                        : {}),
                    ...(clientName ? { mcp_oauth_client_name: clientName } : {}),
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
