import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import guidelines from '@shared/guidelines.md'
import { McpAgent } from 'agents/mcp'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { hasScope } from '@/lib/api'
import { buildToolResultPayload, isToolCallPayload } from '@/lib/build-tool-result'
import { DurableObjectCache } from '@/lib/cache/DurableObjectCache'
import { MCPClientProfile } from '@/lib/client-detection'
import {
    getCustomApiBaseUrl,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getBaseUrlForRegion,
    toCloudRegion,
} from '@/lib/constants'
import { handleToolError, wrapError } from '@/lib/errors'
import { type QueryToolInfo } from '@/lib/instructions'
import { InstructionsFormatter } from '@/lib/instructions-formatter'
import { getPostHogClient } from '@/lib/posthog'
import {
    AnalyticsEvent,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    initMcpAnalytics,
    McpAnalyticsInitResult,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
import { evaluateFeatureFlags, type FlagGroups, isFeatureFlagEnabled } from '@/lib/posthog/flags'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { formatPrompt, type McpMode, sanitizeHeaderValue } from '@/lib/utils'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import { registerUiAppResources } from '@/resources/ui-apps'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import { createExecInnerToolCallResolver, createExecTool, type ExecInnerCallTracker } from '@/tools/exec'
import { getToolDefinition } from '@/tools/toolDefinitions'
import { type CloudRegion, type Context, type State, type Tool } from '@/tools/types'

const instructionsFormatter = new InstructionsFormatter()

export type RequestProperties = {
    userHash: string
    apiToken: string
    // Wrapper-app-provided hint from `?sessionId=` query param. Resolved to a
    // UUID via `SessionManager.getSessionUuid()` and emitted as `$session_id`
    // for Session Replay / AI observability grouping. Only set by wrapping
    // consumer apps (setup wizard, sandbox, etc.).
    sessionId?: string
    // Streamable-HTTP transport session id (`Mcp-Session-Id` HTTP header).
    // Server-minted per the MCP protocol spec, present on every request after
    // initialize. Distinct from `sessionId` above — this is the transport's
    // own correlation key, available for direct MCP clients (Claude Code,
    // Cursor, …) that never set the wrapper-app `?sessionId=` hint.
    mcpSessionId?: string
    // Agent-echoed conversation id from `@posthog/mcp-analytics`'s
    // `enableConversationId: true`. Sourced today from the inbound
    // `mcp-conversation-id` HTTP header (see `index.ts`). Persists across
    // transport reconnects because the agent is asked to echo the value back
    // on every subsequent tool call.
    mcpConversationId?: string
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
    viaSseRedirect?: boolean
    requestStartTime?: number
    mcpAnalyticsInitAction?: McpAnalyticsInitResult['action']
    mcpAnalyticsInitReason?: string
    mcpAnalyticsInitErrorName?: string
    mcpAnalyticsInitErrorMessage?: string
}

export class MCP extends McpAgent<Env> {
    server = new McpServer(
        { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
        { instructions: instructionsFormatter.buildV1Instructions() }
    )

    initialState: State = {
        projectId: undefined,
        orgId: undefined,
        distinctId: undefined,
        region: undefined,
        apiKey: undefined,
        clientName: undefined,
        mcpClientName: undefined,
        mcpClientVersion: undefined,
        mcpProtocolVersion: undefined,
    }

    _cache: DurableObjectCache<State> | undefined

    _api: ApiClient | undefined

    _sessionManager: SessionManager | undefined

    private clientInfoResolved = false
    private mcpClientName: string | undefined
    private mcpClientVersion: string | undefined
    private mcpProtocolVersion: string | undefined
    private mcpMode: McpMode | undefined
    private mcpVersion: number | undefined

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
        const customBaseUrl = getCustomApiBaseUrl()
        if (customBaseUrl) {
            return customBaseUrl
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
                mcpSessionId: this.requestProperties.mcpSessionId,
                mcpConversationId: this.requestProperties.mcpConversationId,
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
        this.rotateCachedApiTokenAndTraces({
            apiToken: props?.apiToken,
            mcpSessionId: props?.mcpSessionId,
            mcpConversationId: props?.mcpConversationId,
        })
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
        this.rotateCachedApiTokenAndTraces({
            apiToken: props?.apiToken,
            mcpSessionId: props?.mcpSessionId,
            mcpConversationId: props?.mcpConversationId,
        })
        await super.updateProps(props)
    }

    /**
     * Refresh the cached ApiClient's per-request config in place. Tool handlers
     * read these fields off `context.api.config` — the captured ApiClient from
     * init() — so replacing the instance would leave those references stale.
     * Mutating in place keeps them pointing at the latest values.
     *
     * Name is intentionally awkward to signal that this method has grown
     * beyond just rotating the apiToken; rename more crisply when a natural
     * grouping emerges.
     *
     * Three fields rotate per inbound request:
     *   - `apiToken` — short-lived OAuth tokens get refreshed across the same
     *     transport session.
     *   - `mcpSessionId` — the `Mcp-Session-Id` HTTP header is *absent* on the
     *     initialize call (where `_api` is first constructed) and present on
     *     every subsequent request. Without this refresh, `_api` would be
     *     pinned to `undefined` for the lifetime of a warm DO and the
     *     `x-posthog-mcp-session-id` header would never be sent.
     *   - `mcpConversationId` — same shape as `mcpSessionId`; sourced from
     *     the inbound `mcp-conversation-id` header (today supplied by wrapper
     *     apps; the `@posthog/mcp-analytics` SDK injects it via tool args, but
     *     that path doesn't land on `requestProperties` yet).
     *
     * No-op when there's no cached client, or when an incoming field is empty
     * (don't overwrite a real value with `undefined`).
     */
    private rotateCachedApiTokenAndTraces(updates: {
        apiToken: string | undefined
        mcpSessionId: string | undefined
        mcpConversationId: string | undefined
    }): void {
        if (!this._api) {
            return
        }
        if (updates.apiToken && this._api.config.apiToken !== updates.apiToken) {
            this._api.config.apiToken = updates.apiToken
        }
        if (updates.mcpSessionId && this._api.config.mcpSessionId !== updates.mcpSessionId) {
            this._api.config.mcpSessionId = updates.mcpSessionId
        }
        if (updates.mcpConversationId && this._api.config.mcpConversationId !== updates.mcpConversationId) {
            this._api.config.mcpConversationId = updates.mcpConversationId
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
                    ...(this.requestProperties.mcpSessionId
                        ? { mcp_session_id: this.requestProperties.mcpSessionId }
                        : {}),
                    ...(this.requestProperties.mcpConversationId
                        ? { mcp_conversation_id: this.requestProperties.mcpConversationId }
                        : {}),
                    ...(this.mcpMode ? { mcp_mode: this.mcpMode } : {}),
                    ...(this.mcpVersion !== undefined ? { mcp_version: this.mcpVersion } : {}),
                    ...contextProperties,
                    ...previousContextProperties,
                    ...properties,
                },
            })
        } catch {
            // skip
        }
    }

    private async getAnalyticsContextSafe(
        context: Pick<Context, 'stateManager'>
    ): Promise<MCPAnalyticsContext | undefined> {
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
            await this.trackEvent(event, properties, analyticsContext ? { context: analyticsContext } : undefined)
        }
        return { ...partialContext, trackEvent }
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

        // User-level flags resolve in parallel with cache seeding. Tool flags are
        // deferred until orgId is known so org-group rollouts evaluate correctly.
        const flagPromise = this.resolveVersionFlag()

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

        // Flag-eval groups mirror analytics `$groups` so per-organization and per-project
        // rollouts evaluate against the same entities — see `buildMCPAnalyticsGroups`.
        const flagAnalyticsContext = await this.getAnalyticsContextSafe(context)
        const flagGroups = flagAnalyticsContext ? buildMCPAnalyticsGroups(flagAnalyticsContext) : undefined
        const toolFlagsPromise = this.resolveToolFeatureFlags(clientVersion, flagGroups)

        const [flagVersion, toolFeatureFlags, _apiKey] = await Promise.all([
            flagPromise,
            toolFlagsPromise,
            // Trigger OAuth introspection so the OAuth client name is cached before the useSingleExec decision below
            context.stateManager.getApiKey(),
        ])

        const oauthClientName = (await this.cache.get('clientName')) || undefined

        const clientProfile = new MCPClientProfile({
            clientName: this.mcpClientName,
            clientVersion: this.mcpClientVersion,
            consumer: this.requestProperties.mcpConsumer,
            oauthClientName,
        })

        const { useSingleExec, version } = this.resolveModeAndVersion({
            mode,
            clientProfile,
            flagVersion,
            clientVersion,
        })

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

        // OAuth introspection ran above (we awaited `getApiKey()` before constructing
        // `clientProfile`), so update the ApiClient with the verified OAuth client
        // name for header forwarding.
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

        const instructionsContext = {
            guidelines,
            groupTypes,
            metadata,
            tools: toolInfos,
            queryTools: queryToolInfos,
            featureFlags: toolFeatureFlags,
        }

        // In single-exec mode, when the client honors the MCP `instructions` field we
        // lift the exec-tool blurb, tool-domain list, query-tool catalog, defined-group
        // types and the active-environment `{metadata}` (user name, project, timezone)
        // out of the `command` description and into `instructions`. Clients that ignore
        // `instructions` (Codex — see `client-detection.ts`) keep today's behavior:
        // empty `instructions`, everything inlined in the `command` description.
        let instructions = ''
        if (supportsInstructions) {
            if (useSingleExec) {
                instructions = instructionsFormatter.buildExecInstructions(instructionsContext)
            } else if (version === 2) {
                instructions = instructionsFormatter.buildV2Instructions(instructionsContext)
            } else {
                instructions = instructionsFormatter.buildV1Instructions(metadata)
            }
        }

        this.server = new McpServer({ name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION }, { instructions })

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
            // When the client honors the `instructions` field, env-context is already
            // delivered there — strip it from the command-parameter description.
            const commandReference = instructionsFormatter.buildExecCommandReference(instructionsContext, {
                stripEnvContext: supportsInstructions,
            })

            const trackInnerCall: ExecInnerCallTracker = (toolName, properties) => {
                this.ctx.waitUntil(
                    (async () => {
                        const freshContext = await this.getAnalyticsContextSafe(await this.getContext())
                        await this.trackEvent(
                            AnalyticsEvent.MCP_TOOL_CALL,
                            { tool_name: toolName, ...properties },
                            freshContext ? { context: freshContext } : undefined
                        )
                    })()
                )
            }

            const execTool = createExecTool(
                allTools,
                context,
                instructionsFormatter.buildExecToolDescription(),
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

        const mcpAnalyticsIdentity = {
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
            // the `mcp-version-2` feature flag), so observability events line up with ours.
            getMcpVersion: async () => version,
            getOAuthClientName: async () => (await this.cache.get('clientName')) || undefined,
            getReadOnly: async () => readOnly,
            getTransport: async () => this.requestProperties.transport,
            getMcpConsumer: async () => this.requestProperties.mcpConsumer,
            getMcpMode: async () => this.mcpMode,
            getMcpSessionId: async () => this.requestProperties.mcpSessionId,
            getMcpConversationId: async () => this.requestProperties.mcpConversationId,
        }

        // In single-exec mode every event's `$mcp_tool_name` is `exec`, so the
        // SDK's `$mcp_tool_description` would be the dispatcher's static text on
        // every call. Resolve the inner tool the agent was actually invoking
        // from the command and surface its name + description as
        // `$mcp_exec_tool_call_name` / `$mcp_exec_tool_call_description`.
        const resolveExecInnerToolCall = useSingleExec ? createExecInnerToolCallResolver(allTools) : undefined

        // In single-exec mode the SDK's $mcp_listed_tool_names collapses to
        // just `exec`, so we can't compute "advertised but never called"
        // (zombie tools) from SDK data alone. Pass the inner-tool catalog
        // here so analytics can attach it as $mcp_exec_inner_tool_names on
        // mcp_tools_list events. Dashboards can then diff it against
        // $mcp_exec_tool_call_name from mcp_tool_call.
        const execInnerToolNames = useSingleExec ? allTools.map((t) => t.name) : undefined

        const initResult = await initMcpAnalytics(this.server, mcpAnalyticsIdentity, {
            contextEnabled: true,
            resolveExecInnerToolCall,
            execInnerToolNames,
            // `get_more_tools` only earns its keep outside single-exec mode — there
            // it lets the model report a gap in our discrete tool catalog. In
            // single-exec mode the wrapper handles every call, so the missing-tool
            // signal has nothing to map to and the extra slot is pure noise.
            reportMissingEnabled: !useSingleExec,
        })

        Object.assign(this.requestProperties, {
            mcpAnalyticsInitAction: initResult.action,
            ...(initResult.action === 'skipped' ? { mcpAnalyticsInitReason: initResult.reason } : {}),
            ...(initResult.action === 'failed'
                ? {
                      mcpAnalyticsInitErrorName: initResult.errorName,
                      mcpAnalyticsInitErrorMessage: initResult.errorMessage,
                  }
                : {}),
        } as RequestProperties)

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
                    has_organization_id: !!organizationId,
                    has_project_id: !!projectId,
                    read_only: !!readOnly,
                    via_sse_redirect: !!this.requestProperties.viaSseRedirect,
                    ...(mode ? { mcp_mode_explicit: mode } : {}),
                    ...(initDurationMs !== undefined ? { init_duration_ms: initDurationMs } : {}),
                },
                analyticsContext ? { context: analyticsContext } : undefined
            )
        )
    }

    /**
     * Decide single-exec mode and the protocol version for this connection,
     * stashing both on the instance so `trackEvent` and observability identity
     * provider can emit `mcp_mode` / `mcp_version` on every downstream event
     * without re-deriving them.
     *
     * Single-exec is restricted to coding agents — Cursor and other clients
     * that render `structuredContent` in their UI need the full per-tool roster,
     * not the wrapped CLI. PostHog's agent wrapper self-identifies via the
     * `x-posthog-mcp-consumer` header and forces single-exec regardless of the
     * wrapped client's reported name. Vibe-coding platforms (Lovable, Replit)
     * are detected by OAuth client name since they typically connect through a
     * generic MCP client wrapper. An explicit `mode` from the caller (header
     * `x-posthog-mcp-mode` or query param `mode`) wins over the client-profile
     * heuristic.
     */
    private resolveModeAndVersion(args: {
        mode: McpMode | undefined
        clientProfile: MCPClientProfile
        flagVersion: number | undefined
        clientVersion: number | undefined
    }): { useSingleExec: boolean; version: number } {
        const { mode, clientProfile, flagVersion, clientVersion } = args
        const useSingleExec =
            mode === 'cli' ||
            (mode !== 'tools' &&
                (clientProfile.isCodingAgent() ||
                    clientProfile.isPostHogCodeConsumer() ||
                    clientProfile.isVibeCodingClient()))
        const version = useSingleExec ? 2 : (flagVersion ?? clientVersion ?? 1)

        this.mcpMode = useSingleExec ? 'cli' : 'tools'
        this.mcpVersion = version

        return { useSingleExec, version }
    }

    private async resolveVersionFlag(): Promise<number | undefined> {
        try {
            const distinctId = await this.getDistinctId()
            return (await isFeatureFlagEnabled('mcp-version-2', distinctId)) ? 2 : undefined
        } catch {
            return undefined
        }
    }

    private async resolveToolFeatureFlags(
        version?: number,
        groups?: FlagGroups
    ): Promise<Record<string, boolean> | undefined> {
        try {
            const { getRequiredFeatureFlags } = await import('@/tools/toolDefinitions')
            const flagKeys = getRequiredFeatureFlags(version)
            if (flagKeys.length === 0) {
                return undefined
            }
            const distinctId = await this.getDistinctId()
            return await evaluateFeatureFlags(flagKeys, distinctId, groups)
        } catch {
            return undefined
        }
    }
}
