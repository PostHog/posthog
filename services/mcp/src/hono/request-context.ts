import { ApiClient } from '@/api/client'
import { MCP_ANALYTICS_SOURCE, MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import { wrapError } from '@/lib/errors'
import { getPostHogClient } from '@/lib/posthog'
import {
    AnalyticsEvent,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
import type { RequestProperties } from '@/lib/request-properties'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import type { Context, Env, State } from '@/tools/types'

import { RedisCache, type RedisLike } from './cache/RedisCache'
import { getCustomApiBaseUrl } from './constants'
import type { ElicitBinding } from './elicit-binding'

export class RequestContext {
    private cacheInstance: RedisCache<State> | undefined
    private apiInstance: ApiClient | undefined
    private sessionManagerInstance: SessionManager | undefined
    private distinctIdPromise: Promise<string> | undefined
    private readonly redis: RedisLike
    private readonly env: Env
    private readonly props: RequestProperties
    /**
     * Per-request slot the dispatcher fills in before invoking a tool
     * handler. The `Context.elicit` closure reads this lazily, so the
     * binding may be set either before or after `getContext()` runs.
     */
    private elicitBinding: ElicitBinding | undefined

    constructor(redis: RedisLike, env: Env, props: RequestProperties) {
        this.redis = redis
        this.env = env
        this.props = props
    }

    /**
     * Install (or replace) the elicit binding for this request. Called by
     * the dispatcher for tool-call requests; no-op for other JSONRPC
     * methods that can't surface elicits.
     */
    setElicitBinding(binding: ElicitBinding | undefined): void {
        this.elicitBinding = binding
    }

    get cache(): RedisCache<State> {
        if (!this.props.userHash) {
            throw new Error('User hash is required to use the cache')
        }
        if (!this.cacheInstance) {
            this.cacheInstance = new RedisCache<State>(this.props.userHash, this.redis)
        }
        return this.cacheInstance
    }

    private async api(): Promise<ApiClient> {
        if (!this.apiInstance) {
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
            this.apiInstance = new ApiClient({
                apiToken: this.props.apiToken,
                baseUrl,
                clientUserAgent: this.props.clientUserAgent,
                mcpClientName: this.props.mcpClientName,
                mcpClientVersion: this.props.mcpClientVersion,
                mcpProtocolVersion: this.props.mcpProtocolVersion,
                mcpConsumer: this.props.mcpConsumer,
            })
        }
        return this.apiInstance
    }

    get sessionManager(): SessionManager {
        if (!this.sessionManagerInstance) {
            this.sessionManagerInstance = new SessionManager(this.cache)
        }
        return this.sessionManagerInstance
    }

    async getSessionUuid(sessionId: string | undefined): Promise<string | undefined> {
        if (!sessionId) {
            return undefined
        }
        return this.sessionManager.getSessionUuid(sessionId)
    }

    getDistinctId(): Promise<string> {
        if (!this.distinctIdPromise) {
            this.distinctIdPromise = this.resolveDistinctId()
        }
        return this.distinctIdPromise
    }

    private async resolveDistinctId(): Promise<string> {
        const cached = await this.cache.get('distinctId')
        if (cached) {
            return cached
        }
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
        const partialContext: Omit<Context, 'trackEvent' | 'elicit'> = {
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
        // `Context.elicit` is exposed as a getter so `if (context.elicit)`
        // tracks the current binding state. The dispatcher installs (or omits)
        // the binding AFTER this method returns, depending on the client's
        // initialize-declared capability. Tool authors get the spec-correct
        // capability check: `undefined` when no binding, a callable when one
        // is installed.
        const self = this
        const ctx: Context = { ...partialContext, trackEvent }
        Object.defineProperty(ctx, 'elicit', {
            enumerable: true,
            configurable: false,
            get(): Context['elicit'] {
                const binding = self.elicitBinding
                if (!binding) {
                    return undefined
                }
                return (params, options) => binding.invoke(params, options)
            },
        })
        // Universal seam. In the legacy pipeline it delegates to `elicit`,
        // which is the binding-backed SSE round-trip. Tools that use the
        // universal API work unchanged when v2026 takes over.
        Object.defineProperty(ctx, 'requestInput', {
            enumerable: true,
            configurable: false,
            get(): Context['requestInput'] {
                const binding = self.elicitBinding
                if (!binding) {
                    return undefined
                }
                return async (params) => {
                    return await binding.invoke({
                        message: params.message,
                        requestedSchema: params.requestedSchema,
                    })
                }
            },
        })
        return ctx
    }

    async getAnalyticsContextSafe(context: Pick<Context, 'stateManager'>): Promise<MCPAnalyticsContext | undefined> {
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
        if (!resolvedContext) {
            return
        }

        const event =
            toolName === 'switch-project'
                ? AnalyticsEvent.MCP_PROJECT_SWITCHED
                : toolName === 'switch-organization'
                  ? AnalyticsEvent.MCP_ORGANIZATION_SWITCHED
                  : undefined
        if (!event) {
            return
        }

        const distinctId = await this.getDistinctId()
        await this.trackEvent(event, {}, resolvedContext, previousContext, distinctId, this.props)
    }

    buildClientProperties(props?: RequestProperties): Record<string, unknown> {
        const p = props ?? this.props
        return {
            $ai_product: 'mcp',
            $mcp_source: MCP_ANALYTICS_SOURCE,
            $mcp_server_name: MCP_SERVER_NAME,
            $mcp_server_version: MCP_SERVER_VERSION,
            $mcp_client_name: p.mcpClientName,
            $mcp_client_version: p.mcpClientVersion,
            $mcp_client_user_agent: p.clientUserAgent,
            $mcp_protocol_version: p.mcpProtocolVersion,
            $mcp_transport: p.transport,
            $mcp_session_id: p.mcpSessionId,
            $mcp_conversation_id: p.mcpConversationId,
            $mcp_consumer: p.mcpConsumer,
            $mcp_mode: p.mode,
            $mcp_region: p.region,
            mcp_runtime: 'hono',
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
                    ...(clientName ? { $mcp_oauth_client_name: clientName } : {}),
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
