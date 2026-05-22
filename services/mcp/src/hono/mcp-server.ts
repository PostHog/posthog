import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { hasScope } from '@/lib/api'
import { buildToolResultPayload, isToolCallPayload } from '@/lib/build-tool-result'
import { MCPClientProfile } from '@/lib/client-detection'
import { handleToolError, wrapError } from '@/lib/errors'
import { type QueryToolInfo } from '@/lib/instructions'
import { InstructionsFormatter } from '@/lib/instructions-formatter'
import { getPostHogClient } from '@/lib/posthog'
import {
    AnalyticsEvent,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    initMcpAnalytics,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
import { evaluateFeatureFlags, type FlagGroups, isFeatureFlagEnabled } from '@/lib/posthog/flags'
import { type RequestProperties } from '@/lib/request-properties'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { formatPrompt, type McpMode } from '@/lib/utils'
import { registerPrompts } from '@/prompts'
import { registerResources } from '@/resources'
import type { ContextMillResource } from '@/resources/manifest-types'
import { registerUiAppResources } from '@/resources/ui-apps'
import EXECUTE_SQL_PROMPT from '@/templates/execute-sql-prompt.md'
import { createExecInnerToolCallResolver, createExecTool, type ExecInnerCallTracker } from '@/tools/exec'
import { getToolDefinition } from '@/tools/toolDefinitions'
import { type Context, type Env, type State, type Tool } from '@/tools/types'

import { RedisCache, type RedisLike } from './cache/RedisCache'
import { getCustomApiBaseUrl, getEnv } from './constants'
import { initDurationSeconds, toolCallDurationSeconds, toolCallsTotal } from './metrics'
import type { ToolCatalog, ToolCatalogFilterOptions } from './tool-catalog'

export interface WarmupData {
    catalog: ToolCatalog
    resourceEntries: readonly ContextMillResource[]
}

export type { RequestProperties }

const instructionsFormatter = new InstructionsFormatter()

type HonoRequestProperties = RequestProperties & {
    mcpAnalyticsInitAction?: 'initialized' | 'skipped' | 'failed' | undefined
    mcpAnalyticsInitReason?: string | undefined
    mcpAnalyticsInitErrorName?: string | undefined
    mcpAnalyticsInitErrorMessage?: string | undefined
}

// Guidelines are generated at build time; optional import so tests and
// unbundled dev runs don't explode when the file is absent.
let _guidelines = ''
try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('@shared/guidelines.md')
    _guidelines = typeof mod === 'string' ? mod : (mod?.default ?? '')
} catch {
    _guidelines = ''
}

export class HonoMcpServer {
    server: McpServer

    private props: HonoRequestProperties

    private _cache: RedisCache<State> | undefined

    private _api: ApiClient | undefined

    private _sessionManager: SessionManager | undefined

    private redis: RedisLike

    private env: Env

    private clientInfoResolved = false
    private mcpClientName: string | undefined
    private mcpClientVersion: string | undefined
    private mcpProtocolVersion: string | undefined
    private mcpMode: McpMode | undefined
    private mcpVersion: number | undefined
    private _warmup: WarmupData | undefined

    constructor(redis: RedisLike, props: RequestProperties, warmup?: WarmupData) {
        this.props = props
        this.redis = redis
        this.env = getEnv()
        this._warmup = warmup
        this.server = new McpServer(
            { name: 'PostHog', version: '1.0.0' },
            { instructions: instructionsFormatter.buildV1Instructions() }
        )
    }

    get requestProperties(): HonoRequestProperties {
        return this.props
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

        const { mcpClientName, mcpClientVersion, mcpProtocolVersion } = this.props
        if (mcpClientName || mcpClientVersion) {
            this.mcpClientName = mcpClientName
            this.mcpClientVersion = mcpClientVersion
            this.mcpProtocolVersion = mcpProtocolVersion
            this.clientInfoResolved = true
        }
    }

    async getBaseUrl(): Promise<string> {
        const customApiBaseUrl = getCustomApiBaseUrl()
        if (customApiBaseUrl) {
            return customApiBaseUrl
        }
        if (process.env.NODE_ENV === 'production') {
            throw new Error(
                'POSTHOG_API_BASE_URL must be set in production — Hono deployments are regional and do not auto-detect.'
            )
        }
        return 'http://localhost:8010'
    }

    async api(): Promise<ApiClient> {
        if (!this._api) {
            const baseUrl = await this.getBaseUrl()
            await this.resolveClientInfo()
            this._api = new ApiClient({
                apiToken: this.props.apiToken,
                baseUrl,
                clientUserAgent: this.props.clientUserAgent,
                mcpClientName: this.mcpClientName,
                mcpClientVersion: this.mcpClientVersion,
                mcpProtocolVersion: this.mcpProtocolVersion,
                mcpConsumer: this.props.mcpConsumer,
            })
        }

        return this._api
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

            await this.resolveClientInfo()

            const clientName = await this.cache.get('clientName')

            const contextProperties = options?.context ? buildMCPContextProperties(options.context) : {}
            const previousContextProperties = options?.previousContext
                ? buildMCPContextProperties(options.previousContext, { prefix: 'previous_' })
                : {}
            const groups = options?.context ? buildMCPAnalyticsGroups(options.context) : {}

            const client = getPostHogClient()
            client.capture({
                distinctId,
                event,
                ...(Object.keys(groups).length > 0 ? { groups } : {}),
                properties: {
                    ...(this.props.sessionId
                        ? {
                              $session_id: await this.sessionManager.getSessionUuid(this.props.sessionId),
                          }
                        : {}),
                    ...(clientName ? { mcp_oauth_client_name: clientName } : {}),
                    ...(this.mcpClientName ? { mcp_client_name: this.mcpClientName } : {}),
                    ...(this.mcpClientVersion ? { mcp_client_version: this.mcpClientVersion } : {}),
                    ...(this.mcpProtocolVersion ? { mcp_protocol_version: this.mcpProtocolVersion } : {}),
                    ...(this.props.mcpConsumer ? { mcp_consumer: this.props.mcpConsumer } : {}),
                    ...(this.props.transport ? { mcp_transport: this.props.transport } : {}),
                    ...(this.props.mcpSessionId ? { mcp_session_id: this.props.mcpSessionId } : {}),
                    ...(this.props.mcpConversationId ? { mcp_conversation_id: this.props.mcpConversationId } : {}),
                    ...(this.mcpMode ? { mcp_mode: this.mcpMode } : {}),
                    ...(this.mcpVersion !== undefined ? { mcp_version: this.mcpVersion } : {}),
                    mcp_runtime: 'hono',
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
                toolCallsTotal.inc({ tool: tool.name, status: 'validation_error' })
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

            const stop = toolCallDurationSeconds.startTimer({ tool: tool.name })
            try {
                const isContextSwitch = tool.name === 'switch-project' || tool.name === 'switch-organization'
                const previousContext = isContextSwitch
                    ? await this.getAnalyticsContextSafe(await this.getContext())
                    : undefined
                const handlerResult = await handler(params)
                if (isContextSwitch) {
                    void this.trackContextSwitchEvent(tool.name, await this.getContext(), previousContext)
                }
                toolCallsTotal.inc({ tool: tool.name, status: 'success' })
                stop({ status: 'success' })
                if (isToolCallPayload(handlerResult)) {
                    return handlerResult
                }
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
                toolCallsTotal.inc({ tool: tool.name, status: 'error' })
                stop({ status: 'error' })
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
        const stopInit = initDurationSeconds.startTimer()
        try {
            await this.initInner()
        } finally {
            stopInit()
        }
    }

    private async initInner(): Promise<void> {
        const _t0 = performance.now()
        const _lap = (label: string): void => {
            const elapsed = performance.now() - _t0
            // oxlint-disable-next-line no-console
            console.log(`[init-profile] ${label.padEnd(40)} +${elapsed.toFixed(0)}ms`)
        }

        const { features, tools, version: clientVersion, organizationId, projectId, readOnly, mode } = this.props

        await this.resolveClientInfo()
        _lap('resolveClientInfo')

        // User-level flags resolve in parallel with cache seeding. Tool flags are
        // deferred until orgId/projectUuid are known so group-scoped rollouts evaluate correctly.
        const flagPromise = this.resolveVersionFlag()
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
        _lap('cache seeding')

        const context = await this.getContext()
        _lap('getContext')

        if (!cachedProjectId) {
            cachedProjectId = await this.cache.get('projectId')
        }

        // Initialize org and project
        if (!cachedProjectId) {
            await context.stateManager.setDefaultOrganizationAndProject()
        }
        _lap('setDefaultOrgAndProject')

        // Flag-eval groups mirror analytics `$groups` so per-organization and per-project
        // rollouts evaluate against the same entities — see `buildMCPAnalyticsGroups`.
        const flagAnalyticsContext = await this.getAnalyticsContextSafe(context)
        const flagGroups = flagAnalyticsContext ? buildMCPAnalyticsGroups(flagAnalyticsContext) : undefined
        const toolFlagsPromise = this.resolveToolFeatureFlags(clientVersion, flagGroups)

        const [flagVersion, toolFeatureFlags, singleExecFlagOn, _apiKey] = await Promise.all([
            flagPromise,
            toolFlagsPromise,
            singleExecPromise,
            context.stateManager.getApiKey(),
        ])
        _lap('flags + getApiKey')

        const oauthClientName = (await this.cache.get('clientName')) || undefined

        const clientProfile = new MCPClientProfile({
            clientName: this.mcpClientName,
            clientVersion: this.mcpClientVersion,
            consumer: this.props.mcpConsumer,
            oauthClientName,
        })

        const { useSingleExec, version } = this.resolveModeAndVersion({
            mode,
            singleExecFlagOn,
            clientProfile,
            flagVersion,
            clientVersion,
        })

        // Fetch group types, metadata, and AI consent in parallel (cache is now seeded)
        const resolvedProjectId = projectId || (await this.cache.get('projectId'))
        const apiKeyScopes = _apiKey?.scopes ?? []
        const [groupTypes, metadata, aiConsentGiven] = await Promise.all([
            resolvedProjectId && hasScope(apiKeyScopes, 'group:read')
                ? context.stateManager.getOrFetchGroupTypes(resolvedProjectId)
                : undefined,
            context.stateManager.getEnvironmentPrompt(),
            context.stateManager.getAiConsentGiven(),
        ])
        _lap('groupTypes + metadata')

        // When project ID is provided, both switch tools are removed (project implies org).
        // When only organization ID is provided, only switch-organization is removed.
        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        // Resolve tools — use pre-built catalog when available, else fall back to full init
        const allTools = await this.resolveTools(context, {
            features,
            tools,
            version,
            excludeTools,
            readOnly,
            featureFlags: toolFeatureFlags,
            scopes: apiKeyScopes,
            aiConsentGiven: aiConsentGiven ?? undefined,
        })
        _lap(`resolveTools (${allTools.length} tools, catalog=${!!this._warmup?.catalog.warmedUp})`)

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
            guidelines: _guidelines,
            groupTypes,
            metadata,
            tools: toolInfos,
            queryTools: queryToolInfos,
            featureFlags: toolFeatureFlags,
        }

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

        this.server = new McpServer({ name: 'PostHog', version: '1.0.0' }, { instructions })
        _lap('new McpServer + instructions')

        // Register prompts and resources — use pre-parsed entries when available
        await registerPrompts(this.server)
        if (this._warmup?.resourceEntries.length) {
            const { registerResourceEntries } = await import('@/resources')
            registerResourceEntries(this.server, this._warmup.resourceEntries)
        } else {
            await registerResources(this.server, context)
        }
        await registerUiAppResources(this.server, context)
        _lap('registerPrompts + registerResources')

        // execute-sql is v2-only. Swap its description with the rich SQL prompt.
        if (version === 2) {
            const sqlTool = allTools.find((t) => t.name === 'execute-sql')
            if (sqlTool) {
                sqlTool.description = formatPrompt(EXECUTE_SQL_PROMPT, { guidelines: _guidelines.trim() })
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
                void (async () => {
                    const freshContext = await this.getAnalyticsContextSafe(await this.getContext())
                    await this.trackEvent(
                        AnalyticsEvent.MCP_TOOL_CALL,
                        { tool_name: toolName, ...properties },
                        freshContext ? { context: freshContext } : undefined
                    )
                })()
            }

            const execTool = createExecTool(
                allTools,
                context,
                instructionsFormatter.buildExecToolDescription(),
                commandReference,
                this.props.mcpConsumer,
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
                this.props.sessionId ? this.sessionManager.getSessionUuid(this.props.sessionId) : undefined,
            getMcpClientName: async () => this.mcpClientName,
            getMcpClientVersion: async () => this.mcpClientVersion,
            getMcpProtocolVersion: async () => this.mcpProtocolVersion,
            // Prefer the cached region (set on init after detection) so we don't miss it
            // when the inbound request didn't include the `region` hint.
            getRegion: async () => (await this.cache.get('region')) ?? this.props.region,
            getAnalyticsContext: async () => this.getAnalyticsContextSafe(await this.getContext()),
            getClientUserAgent: async () => this.props.clientUserAgent,
            // Server-resolved version (may differ from the client-reported one because of
            // the `mcp-version-2` feature flag), so observability events line up with ours.
            getMcpVersion: async () => version,
            getOAuthClientName: async () => (await this.cache.get('clientName')) || undefined,
            getReadOnly: async () => readOnly,
            getTransport: async () => this.props.transport,
            getMcpConsumer: async () => this.props.mcpConsumer,
            getMcpMode: async () => this.mcpMode,
            getMcpSessionId: async () => this.props.mcpSessionId,
            getMcpConversationId: async () => this.props.mcpConversationId,
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

        _lap('registerTools')

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

        Object.assign(this.props, {
            mcpAnalyticsInitAction: initResult.action,
            ...(initResult.action === 'skipped' ? { mcpAnalyticsInitReason: initResult.reason } : {}),
            ...(initResult.action === 'failed'
                ? {
                      mcpAnalyticsInitErrorName: initResult.errorName,
                      mcpAnalyticsInitErrorMessage: initResult.errorMessage,
                  }
                : {}),
        } as HonoRequestProperties)

        const initDurationMs = this.props.requestStartTime ? Date.now() - this.props.requestStartTime : undefined

        // Resolve analytics context from the already-primed cache (getEnvironmentPrompt
        // above populated `cachedProject`/`cachedOrg`), so this is effectively free here.
        const analyticsContext = await this.getAnalyticsContextSafe(context)

        _lap('initMcpAnalytics')

        void this.trackEvent(
            AnalyticsEvent.MCP_INIT,
            {
                tool_count: allTools.length,
                has_organization_id: !!organizationId,
                has_project_id: !!projectId,
                read_only: !!readOnly,
                via_sse_redirect: !!this.props.viaSseRedirect,
                ...(mode ? { mcp_mode_explicit: mode } : {}),
                ...(initDurationMs !== undefined ? { init_duration_ms: initDurationMs } : {}),
            },
            analyticsContext ? { context: analyticsContext } : undefined
        )
    }

    /**
     * Decide single-exec mode and the protocol version for this connection,
     * stashing both on the instance so `trackEvent` and observability identity
     * provider can emit `mcp_mode` / `mcp_version` on every downstream event
     * without re-deriving them.
     */
    private resolveModeAndVersion(args: {
        mode: McpMode | undefined
        singleExecFlagOn: boolean
        clientProfile: MCPClientProfile
        flagVersion: number | undefined
        clientVersion: number | undefined
    }): { useSingleExec: boolean; version: number } {
        const { mode, singleExecFlagOn, clientProfile, flagVersion, clientVersion } = args
        const useSingleExec =
            mode === 'cli' ||
            (mode !== 'tools' &&
                singleExecFlagOn &&
                (clientProfile.isCodingAgent() ||
                    clientProfile.isPostHogCodeConsumer() ||
                    clientProfile.isVibeCodingClient()))
        const version = useSingleExec ? 2 : (flagVersion ?? clientVersion ?? 1)

        this.mcpMode = useSingleExec ? 'cli' : 'tools'
        this.mcpVersion = version

        return { useSingleExec, version }
    }

    private async resolveTools(context: Context, options: ToolCatalogFilterOptions): Promise<Tool<z.ZodObject>[]> {
        if (this._warmup?.catalog.warmedUp) {
            return this._warmup.catalog.getFilteredTools(options) as Tool<z.ZodObject>[]
        }
        const { getToolsFromContext } = await import('@/tools')
        return (await getToolsFromContext(context, options)) as Tool<z.ZodObject>[]
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
