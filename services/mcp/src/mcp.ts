import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import guidelines from '@shared/guidelines.md'
import { McpAgent } from 'agents/mcp'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import {
    AnalyticsEvent,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    evaluateFeatureFlags,
    getPostHogClient,
    isFeatureFlagEnabled,
    type MCPAnalyticsContext,
} from '@/lib/analytics'
import { DurableObjectCache } from '@/lib/cache/DurableObjectCache'
import { clientSupportsListChanged } from '@/lib/clientCapabilities'
import {
    CUSTOM_API_BASE_URL,
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getBaseUrlForRegion,
    toCloudRegion,
} from '@/lib/constants'
import { handleToolError, wrapError } from '@/lib/errors'
import { buildInstructionsV1, buildInstructionsV2 } from '@/lib/instructions'
import { initMcpCatObservability } from '@/lib/mcpcat'
import { formatResponse } from '@/lib/response'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { sanitizeHeaderValue } from '@/lib/utils'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { registerUiAppResources } from '@/resources/ui-apps'
import INSTRUCTIONS_TEMPLATE_V1 from '@/templates/instructions-v1.md'
import INSTRUCTIONS_TEMPLATE_V2 from '@/templates/instructions-v2.md'
import { ENABLED_TOOLSETS_KEY } from '@/tools/toolsets/manage'
import { expandToolsetToFeatures, isBootstrapTool, resolveEnabledFeatures } from '@/tools/toolsets/taxonomy'
import {
    POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY,
    POSTHOG_META_KEY,
    type CloudRegion,
    type Context,
    type State,
    type Tool,
} from '@/tools/types'
import type { AnalyticsMetadata, WithAnalytics } from '@/ui-apps/types'

export type RequestProperties = {
    userHash: string
    apiToken: string
    sessionId?: string
    features?: string[]
    tools?: string[]
    region?: string
    version?: number
    organizationId?: string
    projectId?: string
    clientUserAgent?: string
    readOnly?: boolean
    transport?: 'streamable-http' | 'sse'
    requestStartTime?: number
    /** When true, only expose bootstrap tools + toolsets(action='enable',...)'d tools. */
    progressive?: boolean
    /** Toolset ids to pre-enable on connect (from ?toolsets=a,b URL param). */
    initialToolsets?: string[]
    /**
     * MCP clientInfo.name parsed from the initialize request body in the worker fetch
     * handler — more reliable than `getInitializeRequest()` from inside the DO.
     */
    earlyClientName?: string
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
        enabledToolsets: undefined,
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
        // Token rotation on warm DOs is handled by setName(), which mutates
        // this._api.config.apiToken in place. That keeps references captured
        // during init() — e.g. the `context.api` passed to every tool handler
        // in getContext() — seeing the latest token on subsequent fetches.
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

    /**
     * partyserver's `setName` only re-runs `onStart` (and therefore
     * `updateProps`) on cold-start DOs. On warm DOs it updates the private
     * `#_props` and returns early, leaving our cached `_api.config.apiToken`
     * stale across token rotations for the same `mcp-session-id`. Rotate
     * just the cached token here — leave `this.props` and storage alone.
     */
    async setName(name: string, props?: RequestProperties): Promise<void> {
        this.rotateCachedApiToken(props?.apiToken)
        await super.setName(name, props)
    }

    /**
     * Called by the `agents` SDK on cold start / hibernation wake to persist
     * and hydrate props. Apply the token + `this.props` synchronously BEFORE
     * awaiting storage: the SDK fires `updateProps` without awaiting and then
     * calls `fetch()`, so yielding first would let a tool handler read stale
     * state off `context.api.config.apiToken`.
     */
    async updateProps(props?: RequestProperties): Promise<void> {
        this.props = props as RequestProperties
        this.rotateCachedApiToken(props?.apiToken)
        await super.updateProps(props)
    }

    /**
     * Rotate the cached ApiClient's auth token in place. Tool handlers read
     * the token off `context.api.config.apiToken` — the captured ApiClient
     * from init() — so replacing the instance would leave those references
     * stale. Mutating in place keeps them pointing at the latest token.
     * No-op when there's no cached client, no incoming token, or the token
     * already matches.
     */
    private rotateCachedApiToken(apiToken: string | undefined): void {
        if (this._api && apiToken && this._api.config.apiToken !== apiToken) {
            this._api.config.apiToken = apiToken
        }
    }

    async getDistinctId(): Promise<string> {
        let _distinctId = await this.cache.get('distinctId')

        if (!_distinctId) {
            const userResult = await (await this.api()).users().me()
            if (!userResult.success) {
                throw wrapError(`Failed to get user: ${userResult.error.message}`, userResult.error)
            }
            await this.cache.set('distinctId', userResult.data.distinct_id)
            _distinctId = userResult.data.distinct_id as string
        }

        return _distinctId
    }

    async trackEvent(
        event: AnalyticsEvent,
        properties: Record<string, any> = {},
        options?: { context?: MCPAnalyticsContext; previousContext?: MCPAnalyticsContext }
    ): Promise<void> {
        try {
            const distinctId = await this.getDistinctId()

            const client = getPostHogClient()

            await this.resolveClientInfo()

            const clientName = await this.cache.get('clientName')

            const contextProperties = options?.context ? buildMCPContextProperties(options.context) : {}
            const previousContextProperties = options?.previousContext
                ? buildMCPContextProperties(options.previousContext, { prefix: 'previous_' })
                : {}
            const groups = options?.context ? buildMCPAnalyticsGroups(options.context) : {}

            // `groups` is translated to `$groups` server-side by posthog-node. No separate
            // `groupIdentify` call: org/project group properties are populated by the main
            // PostHog backend (see `posthog/event_usage.py`), and duplicating them from here
            // with the minimal info we have would overwrite richer core-owned data.
            client.capture({
                distinctId,
                event,
                ...(Object.keys(groups).length > 0 ? { groups } : {}),
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
                    ...contextProperties,
                    ...previousContextProperties,
                    ...properties,
                },
            })
        } catch {
            // skip
        }
    }

    private async getAnalyticsContextSafe(context: Context): Promise<MCPAnalyticsContext | undefined> {
        try {
            return await context.stateManager.getAnalyticsContext()
        } catch {
            return undefined
        }
    }

    private async trackContextSwitchEvent(
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

        await this.trackEvent(
            event,
            {},
            { context: resolvedContext, ...(previousContext ? { previousContext } : {}) }
        )
    }

    /**
     * Map of tool-name → RegisteredTool returned by `McpServer.registerTool()`. Used by the
     * `toolsets` meta-tool to flip individual tools `.enable()`/`.disable()` at runtime, which
     * the SDK surfaces via `tools/list` filtering + auto-fired `notifications/tools/list_changed`.
     */
    _toolRegistrations: Map<string, { enable: () => void; disable: () => void }> = new Map()

    registerTool<TSchema extends z.ZodObject>(
        tool: Tool<TSchema>,
        handler: (params: z.infer<TSchema>) => Promise<any>
    ): { enable: () => void; disable: () => void } {
        const wrappedHandler = async (params: z.infer<TSchema>): Promise<any> => {
            const validation = tool.schema.safeParse(params)

            if (!validation.success) {
                const errorOutput = `Invalid input: ${validation.error.message}`

                return {
                    content: [
                        {
                            type: 'text',
                            text: errorOutput,
                        },
                    ],
                }
            }

            try {
                const isContextSwitch = tool.name === 'switch-project' || tool.name === 'switch-organization'
                const previousContext = isContextSwitch
                    ? await this.getAnalyticsContextSafe(await this.getContext())
                    : undefined
                // Handler can return a special key POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY in the result which,
                // when present, is used as the text content instead of TOON-encoding the raw result.
                // This is useful for tools that want to return pre-formatted text (e.g. tables)
                // or return JSON for programmatic consumption.
                const handlerResult = await handler(params)
                if (isContextSwitch) {
                    this.ctx.waitUntil(
                        this.trackContextSwitchEvent(tool.name, await this.getContext(), previousContext)
                    )
                }
                // Guard against string results: object rest on a primitive string would
                // expand it to a character-indexed object ({"0": "f", "1": "o", ...}).
                const isStringResult = typeof handlerResult === 'string'
                const formattedResults: string | undefined = isStringResult
                    ? undefined
                    : handlerResult?.[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]
                let rawResult: any
                if (isStringResult) {
                    rawResult = handlerResult
                } else {
                    const { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: _ignored, ...rest } = handlerResult
                    rawResult = rest
                }

                // For tools with UI resources, include structuredContent for better UI rendering
                // structuredContent is not added to model context, only used by UI apps
                const hasUiResource = tool._meta?.ui?.resourceUri

                // If there's a UI resource, include analytics metadata for the UI app
                let structuredContent: WithAnalytics<typeof rawResult> | typeof rawResult = rawResult
                if (hasUiResource && !isStringResult) {
                    const distinctId = await this.getDistinctId()
                    const analyticsMetadata: AnalyticsMetadata = {
                        distinctId,
                        toolName: tool.name,
                    }
                    structuredContent = {
                        ...rawResult,
                        _analytics: analyticsMetadata,
                    }
                }

                const useJson = tool._meta?.[POSTHOG_META_KEY]?.responseFormat === 'json'
                const text = formattedResults ?? (useJson ? JSON.stringify(rawResult) : formatResponse(rawResult))

                return {
                    content: [
                        {
                            type: 'text',
                            text,
                        },
                    ],
                    // Include raw result as structuredContent for UI apps to consume only in case there is a UI resource
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

        const registered = this.server.registerTool(
            tool.name,
            {
                title: tool.title,
                description: tool.description,
                inputSchema: tool.schema.shape,
                annotations: tool.annotations,
                ...(normalizedMeta ? { _meta: normalizedMeta } : {}),
            },
            wrappedHandler as unknown as ToolCallback<TSchema['shape']>
        ) as unknown as { enable: () => void; disable: () => void }
        this._toolRegistrations.set(tool.name, registered)
        return registered
    }

    /**
     * Flip `_toolRegistrations` enabled state for every tool whose feature is covered by
     * `toolsetId` (either a base toolset = 1 feature, or a composite = many features).
     * The SDK auto-fires `notifications/tools/list_changed` on each `.enable()`/`.disable()`,
     * so compatible MCP clients re-request `tools/list` and see the updated catalog.
     */
    applyToolsetToRegistrations(
        toolsetId: string | undefined,
        action: 'enable' | 'disable',
        toolDefs: Record<string, { feature: string }>,
        version?: number
    ): void {
        if (!toolsetId) {
            return
        }
        const features = new Set(expandToolsetToFeatures(toolsetId, version))
        if (features.size === 0) {
            return
        }
        for (const [name, registered] of this._toolRegistrations.entries()) {
            // Bootstrap tools are always visible regardless of toolset state. Never flip them.
            if (isBootstrapTool(name)) {
                continue
            }
            const def = toolDefs[name]
            if (!def) {
                continue
            }
            if (!features.has(def.feature)) {
                continue
            }
            if (action === 'enable') {
                registered.enable()
            } else {
                registered.disable()
            }
        }
    }

    /**
     * Fire a `notifications/tools/list_changed` MCP notification so compatible clients
     * re-request `tools/list`. Best-effort: swallow errors since the transport may not
     * support notifications at all.
     */
    notifyToolListChanged(): void {
        try {
            const underlying = (this.server as any)?.server
            if (underlying && typeof underlying.sendToolListChanged === 'function') {
                underlying.sendToolListChanged()
            }
        } catch {
            // best-effort
        }
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
        const {
            features,
            tools,
            version: clientVersion,
            organizationId,
            projectId,
            readOnly,
            progressive,
            initialToolsets,
            earlyClientName,
        } = this.requestProperties

        // Stash clientInfo captured from the initialize body so progressive-mode tool calls
        // can detect known-unsupported clients even across requests in the same session.
        // Bypassing the State type here because the cache union is already crowded with
        // per-feature prefix-keys; mcpClientName is a simple string lookup.
        const cacheUntyped = this.cache as unknown as {
            get: (k: string) => Promise<unknown>
            set: (k: string, v: unknown) => Promise<void>
        }
        if (earlyClientName) {
            this._mcpClientName = earlyClientName
            await cacheUntyped.set('mcpClientName', earlyClientName)
        } else {
            const cached = await cacheUntyped.get('mcpClientName')
            if (typeof cached === 'string') {
                this._mcpClientName = cached
            }
        }

        // Start feature flag resolution in parallel with cache seeding
        const flagPromise = this.resolveVersionFlag()
        const toolFlagsPromise = this.resolveToolFeatureFlags(clientVersion)

        // Seed cache with header-provided IDs before any fetches
        if (organizationId) {
            await this.cache.set('orgId', organizationId)
        }
        if (projectId) {
            await this.cache.set('projectId', projectId)
        }

        const context = await this.getContext()

        // Resolve defaults if headers didn't provide org/project
        if (!organizationId || !projectId) {
            await context.stateManager.setDefaultOrganizationAndProject()
        }

        const [flagVersion, toolFeatureFlags] = await Promise.all([flagPromise, toolFlagsPromise])
        const version = flagVersion ?? clientVersion ?? 1

        // Fetch group types and metadata in parallel (cache is now seeded)
        const resolvedProjectId = projectId || (await this.cache.get('projectId'))
        const [groupTypes, metadata] = await Promise.all([
            resolvedProjectId
                ? context.stateManager.getOrFetchGroupTypes(resolvedProjectId)
                : Promise.resolve(undefined),
            context.stateManager.getEnvironmentPrompt(),
        ])
        const instructions =
            version === 2
                ? buildInstructionsV2(INSTRUCTIONS_TEMPLATE_V2, guidelines, groupTypes, metadata)
                : buildInstructionsV1(INSTRUCTIONS_TEMPLATE_V1, metadata)

        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions })

        // When project ID is provided, both switch tools are removed (project implies org).
        // When only organization ID is provided, only switch-organization is removed.
        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        // Register prompts and resources
        await Promise.all([
            registerPrompts(this.server),
            registerResources(this.server, context),
            registerUiAppResources(this.server, context),
        ])

        // Register tools. In progressive mode we still fetch the full catalog (so we can
        // dynamically `.enable()` tools on demand without needing to re-init the session),
        // then disable non-bootstrap, non-enabled ones below.
        const { getToolsFromContext } = await import('@/tools')
        const allTools = await getToolsFromContext(context, {
            features,
            tools,
            version,
            excludeTools,
            readOnly,
            featureFlags: toolFeatureFlags,
        })

        // OAuth introspection has now run (triggered by getToolsFromContext → getApiKey),
        // so update the ApiClient with the verified OAuth client name for header forwarding.
        const oauthClientName = (await this.cache.get('clientName')) || undefined
        if (oauthClientName && this._api) {
            this._api.config.oauthClientName = oauthClientName
        }

        const { getToolDefinitions } = await import('@/tools/toolDefinitions')
        const toolDefs = getToolDefinitions(version)

        // Resolve the set of FEATURES that should be active at init time: merge session
        // cache with any ?toolsets=<ids> query-param pre-enables, then expand composites.
        const sessionEnabled = ((await this.cache.get(ENABLED_TOOLSETS_KEY as any)) ?? []) as string[]
        const initialEnabledToolsets = Array.from(new Set([...sessionEnabled, ...(initialToolsets ?? [])]))
        const initialEnabledFeatures = resolveEnabledFeatures(initialEnabledToolsets, version)

        // Persist ?toolsets= pre-enables so a subsequent toolsets(action='list') reflects reality.
        if (initialEnabledToolsets.length !== sessionEnabled.length) {
            await this.cache.set(ENABLED_TOOLSETS_KEY as any, initialEnabledToolsets as any)
        }

        for (const tool of allTools) {
            const typedTool = tool as Tool<z.ZodObject>
            const registered = this.registerTool(typedTool, async (params) => typedTool.handler(context, params))

            // In progressive mode, disable everything that isn't bootstrap and whose feature
            // isn't already active (via session cache or ?toolsets= pre-enable). Keep the
            // registration so `toolsets(action='enable')` can `.enable()` it later without
            // needing a full re-init.
            if (progressive) {
                if (isBootstrapTool(typedTool.name)) {
                    continue
                }
                const def = toolDefs[typedTool.name]
                const feature = def?.feature
                if (!feature || !initialEnabledFeatures.has(feature)) {
                    registered.disable()
                }
            }
        }

        // Register the `toolsets` meta-tool explicitly in progressive mode. It isn't returned
        // by getToolsFromContext (always excluded there so the default tool surface is
        // unchanged), so we construct it from TOOL_MAP + toolDefs here.
        if (progressive) {
            const { TOOL_MAP, buildTool } = await import('@/tools')
            const toolsetsFactory = TOOL_MAP.toolsets
            if (toolsetsFactory) {
                const toolsetsTool = buildTool(toolsetsFactory(), version) as Tool<z.ZodObject>
                this.registerTool(toolsetsTool, async (params: any) => {
                    const result = (await toolsetsTool.handler(context, params)) as Record<string, unknown>
                    if (params?.action === 'enable' || params?.action === 'disable') {
                        this.applyToolsetToRegistrations(params.name, params.action, toolDefs, version)
                        await this.resolveClientInfo()
                        if (!clientSupportsListChanged(this._mcpClientName)) {
                            const enabled = ((await context.cache.get(ENABLED_TOOLSETS_KEY as any)) ?? []) as string[]
                            const reconnectQuery = `?progressive=true${enabled.length ? `&toolsets=${enabled.join(',')}` : ''}`
                            const symptom =
                                params.action === 'enable'
                                    ? "newly enabled tools aren't visible"
                                    : 'disabled tools are still visible'
                            return {
                                ...result,
                                _reconnectHint: `Your MCP client may not auto-refresh the tool list. If ${symptom} next turn, ask the user to reconnect with: ${reconnectQuery}`,
                            }
                        }
                    }
                    return result
                })
            }
        }

        await initMcpCatObservability(this.server, {
            getDistinctId: () => this.getDistinctId(),
            getSessionUuid: async () =>
                this.requestProperties.sessionId
                    ? this.sessionManager.getSessionUuid(this.requestProperties.sessionId)
                    : undefined,
            getMcpClientName: async () => this._mcpClientName,
            getMcpClientVersion: async () => this._mcpClientVersion,
            getMcpProtocolVersion: async () => this._mcpProtocolVersion,
            // Prefer the cached region (set on init after detection) so we don't miss it
            // when the inbound request didn't include the `region` hint.
            getRegion: async () => (await this.cache.get('region')) ?? this.requestProperties.region,
            getAnalyticsContext: async () => this.getAnalyticsContextSafe(await this.getContext()),
            getClientUserAgent: async () => this.requestProperties.clientUserAgent,
            // Server-resolved version (may differ from the client-reported one because of
            // the `mcp-version-2` feature flag), so mcpcat events line up with ours.
            getVersion: async () => version,
            getOAuthClientName: async () => (await this.cache.get('clientName')) || undefined,
            getReadOnly: async () => readOnly,
            getTransport: async () => this.requestProperties.transport,
        })

        const initDurationMs = this.requestProperties.requestStartTime
            ? Date.now() - this.requestProperties.requestStartTime
            : undefined

        // Resolve analytics context from the already-primed cache (getEnvironmentPrompt
        // above populated `cachedProject`/`cachedOrg`), so this is effectively free here.
        const analyticsContext = await this.getAnalyticsContextSafe(context)

        this.ctx.waitUntil(
            this.trackEvent(
                AnalyticsEvent.MCP_INIT,
                {
                    tool_count: allTools.length,
                    mcp_version: version,
                    has_organization_id: !!organizationId,
                    has_project_id: !!projectId,
                    read_only: !!readOnly,
                    ...(initDurationMs !== undefined ? { init_duration_ms: initDurationMs } : {}),
                },
                analyticsContext ? { context: analyticsContext } : undefined
            )
        )
    }

    private async resolveVersionFlag(): Promise<number | undefined> {
        try {
            const distinctId = await this.getDistinctId()
            return (await isFeatureFlagEnabled('mcp-version-2', distinctId)) ? 2 : undefined
        } catch {
            return undefined
        }
    }

    private async resolveToolFeatureFlags(version?: number): Promise<Record<string, boolean> | undefined> {
        try {
            const { getRequiredFeatureFlags } = await import('@/tools/toolDefinitions')
            const flagKeys = getRequiredFeatureFlags(version)
            if (flagKeys.length === 0) {
                return undefined
            }
            const distinctId = await this.getDistinctId()
            return await evaluateFeatureFlags(flagKeys, distinctId)
        } catch {
            return undefined
        }
    }
}
