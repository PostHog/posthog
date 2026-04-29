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
import { hasScope } from '@/lib/api'
import { buildToolResultPayload, isToolCallPayload } from '@/lib/build-tool-result'
import { DurableObjectCache } from '@/lib/cache/DurableObjectCache'
import { MCPClientProfile } from '@/lib/client-detection'
import {
    CUSTOM_API_BASE_URL,
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getBaseUrlForRegion,
    toCloudRegion,
} from '@/lib/constants'
import { handleToolError, wrapError } from '@/lib/errors'
import { buildInstructionsV1, buildInstructionsV2, type QueryToolInfo } from '@/lib/instructions'
import { initMcpCatObservability } from '@/lib/mcpcat'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { formatPrompt, type McpMode, sanitizeHeaderValue } from '@/lib/utils'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { registerUiAppResources } from '@/resources/ui-apps'
import CLI_PROXY_COMMAND from '@/templates/cli-proxy-command.md'
import CLI_PROXY_TOOL from '@/templates/cli-proxy-tool.md'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import INSTRUCTIONS_TEMPLATE_V1 from '@/templates/instructions-v1.md'
import INSTRUCTIONS_TEMPLATE_V2 from '@/templates/instructions-v2.md'
import SINGLE_EXEC_INSTRUCTIONS from '@/templates/single-exec-instructions.md'
import { createExecTool, type ExecInnerCallTracker } from '@/tools/exec'
import { getToolDefinition } from '@/tools/toolDefinitions'
import { type CloudRegion, type Context, type State, type Tool } from '@/tools/types'

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
    mcpConsumer?: string
    mcpClientName?: string
    mcpClientVersion?: string
    mcpProtocolVersion?: string
    readOnly?: boolean
    mode?: McpMode
    transport?: 'streamable-http' | 'sse'
    requestStartTime?: number
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
    }

    _cache: DurableObjectCache<State> | undefined

    _api: ApiClient | undefined

    _sessionManager: SessionManager | undefined

    private clientInfoResolved = false
    private mcpClientName: string | undefined
    private mcpClientVersion: string | undefined
    private mcpProtocolVersion: string | undefined

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
        if (this.clientInfoResolved) {
            return
        }

        // Prefer values parsed from the current request body (see
        // `extractClientInfoFromBody` in index.ts). This is the only path
        // that works during init(), because the framework's async
        // `getInitializeRequest()` reads DO storage which is only written
        // *after* `onStart`/`init()` has run.
        const { mcpClientName, mcpClientVersion, mcpProtocolVersion } = this.requestProperties
        if (mcpClientName || mcpClientVersion) {
            this.mcpClientName = mcpClientName
            this.mcpClientVersion = mcpClientVersion
            this.mcpProtocolVersion = mcpProtocolVersion
            this.clientInfoResolved = true
            return
        }

        // Fallback: read the saved initialize message from DO storage.
        // Post-init only — during init() this storage write has not landed.
        try {
            const initRequest = await this.getInitializeRequest()
            if (!initRequest || !('params' in initRequest)) {
                return
            }

            const params = (
                initRequest as {
                    params?: {
                        clientInfo?: { name?: string; version?: string }
                        protocolVersion?: string
                    }
                }
            ).params
            if (!params) {
                return
            }

            this.mcpClientName = sanitizeHeaderValue(params.clientInfo?.name)
            this.mcpClientVersion = sanitizeHeaderValue(params.clientInfo?.version)
            this.mcpProtocolVersion = sanitizeHeaderValue(params.protocolVersion)
            this.clientInfoResolved = true
        } catch (error) {
            // stay unresolved so a later caller can retry
            console.error('[MCP] resolveClientInfo fallback failed:', error)
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
                mcpClientName: this.mcpClientName,
                mcpClientVersion: this.mcpClientVersion,
                mcpProtocolVersion: this.mcpProtocolVersion,
                mcpConsumer: this.requestProperties.mcpConsumer,
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
                    ...(this.mcpClientName ? { mcp_client_name: this.mcpClientName } : {}),
                    ...(this.mcpClientVersion ? { mcp_client_version: this.mcpClientVersion } : {}),
                    ...(this.mcpProtocolVersion ? { mcp_protocol_version: this.mcpProtocolVersion } : {}),
                    ...(this.requestProperties.mcpConsumer ? { mcp_consumer: this.requestProperties.mcpConsumer } : {}),
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

        await this.trackEvent(event, {}, { context: resolvedContext, ...(previousContext ? { previousContext } : {}) })
    }

    registerTool<TSchema extends z.ZodObject>(
        tool: Tool<TSchema>,
        handler: (params: z.infer<TSchema>) => Promise<any>
    ): void {
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
                const handlerResult = await handler(params)
                if (isContextSwitch) {
                    this.ctx.waitUntil(
                        this.trackContextSwitchEvent(tool.name, await this.getContext(), previousContext)
                    )
                }
                // The exec wrapper (single-exec mode) assembles the per-call payload itself —
                // propagating the inner tool's UI resourceUri onto the response — so pass it
                // through unchanged. Re-running `buildToolResultPayload` on the payload would
                // object-rest-destructure its content/structuredContent fields.
                if (isToolCallPayload(handlerResult)) {
                    return handlerResult
                }
                // Fetch distinctId only when a UI-resource tool with a non-string result might
                // actually use it in structuredContent; avoids an extra round-trip otherwise.
                const hasUiResource = !!tool._meta?.ui?.resourceUri
                const needsDistinctId = hasUiResource && typeof handlerResult !== 'string'
                const distinctId = needsDistinctId ? await this.getDistinctId() : undefined

                return buildToolResultPayload({
                    handlerResult,
                    toolMeta: tool._meta,
                    toolName: tool.name,
                    params,
                    clientName: this.mcpClientName,
                    distinctId,
                })
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
            getDistinctId: () => this.getDistinctId(),
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
            mode,
        } = this.requestProperties

        // Resolve MCP client info before any code reads it — most importantly
        // the `useSingleExec` decision below. During init() this resolves from
        // request properties (populated by `extractClientInfoFromBody` at the
        // worker entry point); the DO-storage fallback inside
        // `resolveClientInfo` is only reachable post-init.
        await this.resolveClientInfo()

        const clientProfile = new MCPClientProfile({
            clientName: this.mcpClientName,
            clientVersion: this.mcpClientVersion,
            consumer: this.requestProperties.mcpConsumer,
        })

        // Start feature flag resolution in parallel with cache seeding
        const flagPromise = this.resolveVersionFlag()
        const toolFlagsPromise = this.resolveToolFeatureFlags(clientVersion)
        const singleExecPromise = this.resolveSingleExecFlag()

        // Seed cache with header-provided IDs before any fetches
        if (organizationId) {
            await this.cache.set('orgId', organizationId)
        }
        let cachedProjectId: string | undefined
        if (projectId) {
            cachedProjectId = projectId
            await this.cache.set('projectId', projectId)
        }

        const context = await this.getContext()
        // Sticky session: skip default resolution if a previous init for this
        // userHash already picked a project (cache survives DO cold-restarts).
        // Without this guard, switching the active org in the user's browser
        // would silently reshuffle an established Claude session — `users/@me`
        // returns whatever team the browser currently has selected, and
        // setDefaultOrganizationAndProject would overwrite the cache with it.
        // Headers always win because they were applied to the cache above.
        if (!cachedProjectId) {
            cachedProjectId = await this.cache.get('projectId')
        }

        // Initialize org and project
        if (!cachedProjectId) {
            await context.stateManager.setDefaultOrganizationAndProject()
        }

        const [flagVersion, toolFeatureFlags, singleExecFlagOn] = await Promise.all([
            flagPromise,
            toolFlagsPromise,
            singleExecPromise,
        ])

        // Restrict single-exec mode to coding agents only — Cursor and other clients that
        // render `structuredContent` in their UI need the full per-tool roster, not the
        // wrapped CLI. `resolveClientInfo` is awaited at the top of `init()` so this
        // decision sees the real value on first-connect. PostHog's agent wrapper
        // self-identifies via the `x-posthog-mcp-consumer` header and forces
        // single-exec regardless of the wrapped client's reported name.
        // An explicit `mode` from the caller (header `x-posthog-mcp-mode` or query
        // param `mode`) wins over the flag + client-profile heuristic.
        const useSingleExec =
            mode === 'cli' ||
            (mode !== 'tools' &&
                singleExecFlagOn &&
                (clientProfile.isCodingAgent() || clientProfile.isPostHogCodeConsumer()))
        const version = useSingleExec ? 2 : (flagVersion ?? clientVersion ?? 1)

        // Fetch group types and metadata in parallel (cache is now seeded)
        const resolvedProjectId = projectId || (await this.cache.get('projectId'))
        const [groupTypes, metadata] = await Promise.all([
            (async () => {
                if (!resolvedProjectId) {
                    return undefined
                }
                const apiKey = await context.stateManager.getApiKey()
                return hasScope(apiKey.scopes, 'group:read')
                    ? context.stateManager.getOrFetchGroupTypes(resolvedProjectId)
                    : undefined
            })(),
            context.stateManager.getEnvironmentPrompt(),
        ])
        // When project ID is provided, both switch tools are removed (project implies org).
        // When only organization ID is provided, only switch-organization is removed.
        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        // Fetch tools up-front so we can build the query tool catalog (and the
        // CLI exec tool's domain list) before constructing the system prompt.
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

        const toolInfos = allTools.map((t) => ({
            name: t.name,
            category: getToolDefinition(t.name, version).category,
        }))
        const queryToolInfos: QueryToolInfo[] = allTools
            .filter((t) => t.name.startsWith('query-'))
            .map((t) => {
                const def = getToolDefinition(t.name, version)
                return {
                    name: t.name,
                    title: def.title,
                    ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                }
            })

        const supportsInstructions = clientProfile.capabilities.supportsInstructions

        // In single-exec mode, when the client honors the MCP `instructions` field we
        // lift the exec-tool blurb, tool-domain list, query-tool catalog, defined-group
        // types and the active-environment `{metadata}` (user name, project, timezone)
        // out of the `command` description and into `instructions`. Clients that ignore
        // `instructions` (Codex — see `client-detection.ts`) keep today's behavior:
        // empty `instructions`, everything inlined in the `command` description.
        let instructions = ''
        if (supportsInstructions) {
            if (useSingleExec) {
                instructions = buildInstructionsV2(
                    SINGLE_EXEC_INSTRUCTIONS,
                    guidelines,
                    groupTypes,
                    metadata,
                    toolInfos,
                    queryToolInfos,
                    { compact: true }
                )
            } else {
                instructions =
                    version === 2
                        ? buildInstructionsV2(
                              INSTRUCTIONS_TEMPLATE_V2,
                              guidelines,
                              groupTypes,
                              metadata,
                              toolInfos,
                              queryToolInfos
                          )
                        : buildInstructionsV1(INSTRUCTIONS_TEMPLATE_V1, metadata)
            }
        }

        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions })

        // Register prompts and resources
        await Promise.all([
            registerPrompts(this.server),
            registerResources(this.server, context),
            registerUiAppResources(this.server, context),
        ])

        // execute-sql is v2-only. Swap its description with the rich SQL prompt
        // (visible via `info execute-sql` in single-exec, and as the tool's own
        // description otherwise). It folds in the HogQL/SQL intro, guidelines,
        // discovery workflow, and the truncation guidance that the base JSON
        // description carried — and it triggers the `querying-posthog-data`
        // skill more reliably than the shorter default.
        if (version === 2) {
            const sqlTool = allTools.find((t) => t.name === 'execute-sql')
            if (sqlTool) {
                sqlTool.description = formatPrompt(EXECUTE_SQL_PROMPT, { guidelines: guidelines.trim() })
            }
        }

        // In single-exec mode, register one "posthog" tool that wraps all tools
        // behind a CLI-like interface. Otherwise, register each tool individually.
        if (useSingleExec) {
            // Strip `{tool_domains}`, `{query_tools}`, `{defined_groups}`, `{metadata}`
            // from the command-parameter description when they're already in `instructions`
            // (their placeholders resolve to empty strings via `buildInstructionsV2`).
            const commandReference = buildInstructionsV2(
                CLI_PROXY_COMMAND,
                guidelines,
                supportsInstructions ? undefined : groupTypes,
                supportsInstructions ? undefined : metadata,
                supportsInstructions ? undefined : toolInfos,
                supportsInstructions ? undefined : queryToolInfos
            )

            const trackInnerCall: ExecInnerCallTracker = (toolName, properties) => {
                this.ctx.waitUntil(
                    (async () => {
                        const freshContext = await this.getAnalyticsContextSafe(await this.getContext())
                        await this.trackEvent(
                            AnalyticsEvent.MCP_TOOL_CALLED,
                            { tool_name: toolName, ...properties },
                            freshContext ? { context: freshContext } : undefined
                        )
                    })()
                )
            }

            const execTool = createExecTool(
                allTools,
                context,
                CLI_PROXY_TOOL,
                commandReference,
                this.requestProperties.mcpConsumer,
                trackInnerCall
            )
            const typedExecTool = execTool as Tool<z.ZodObject>
            this.registerTool(typedExecTool, async (params) => typedExecTool.handler(context, params))
        } else {
            for (const tool of allTools) {
                const typedTool = tool as Tool<z.ZodObject>
                this.registerTool(typedTool, async (params) => typedTool.handler(context, params))
            }
        }

        await initMcpCatObservability(this.server, {
            getDistinctId: () => this.getDistinctId(),
            getSessionUuid: async () =>
                this.requestProperties.sessionId
                    ? this.sessionManager.getSessionUuid(this.requestProperties.sessionId)
                    : undefined,
            getMcpClientName: async () => this.mcpClientName,
            getMcpClientVersion: async () => this.mcpClientVersion,
            getMcpProtocolVersion: async () => this.mcpProtocolVersion,
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
                    mcp_mode: useSingleExec ? 'cli' : 'tools',
                    has_organization_id: !!organizationId,
                    has_project_id: !!projectId,
                    read_only: !!readOnly,
                    ...(mode ? { mcp_mode_explicit: mode } : {}),
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

    private async resolveSingleExecFlag(): Promise<boolean> {
        try {
            const distinctId = await this.getDistinctId()
            return !!(await isFeatureFlagEnabled('mcp-single-exec-tool', distinctId))
        } catch {
            return false
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
