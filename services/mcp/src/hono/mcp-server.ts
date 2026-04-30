import { RESOURCE_URI_META_KEY } from '@modelcontextprotocol/ext-apps/server'
import { McpServer, type ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js'
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
import { buildToolResultPayload, isToolCallPayload } from '@/lib/build-tool-result'
import { MCPClientProfile } from '@/lib/client-detection'
import { handleToolError, wrapError } from '@/lib/errors'
import { buildInstructionsV1, buildInstructionsV2, type QueryToolInfo } from '@/lib/instructions'
import { initMcpCatObservability } from '@/lib/mcpcat'
import { type RequestProperties } from '@/lib/request-properties'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import { formatPrompt, sanitizeHeaderValue } from '@/lib/utils'
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
import { type CloudRegion, type Context, type Env, type State, type Tool } from '@/tools/types'

import { RedisCache, type RedisLike } from './cache/RedisCache'
import {
    getCustomApiBaseUrl,
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getBaseUrlForRegion,
    getEnv,
    toCloudRegion,
} from './constants'

export type { RequestProperties }

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

    private props: RequestProperties

    private _cache: RedisCache<State> | undefined

    private _api: ApiClient | undefined

    private _sessionManager: SessionManager | undefined

    private redis: RedisLike

    private env: Env

    private clientInfoResolved = false
    private mcpClientName: string | undefined
    private mcpClientVersion: string | undefined
    private mcpProtocolVersion: string | undefined

    constructor(redis: RedisLike, props: RequestProperties) {
        this.props = props
        this.redis = redis
        this.env = getEnv()
        this.server = new McpServer(
            { name: 'PostHog', version: '1.0.0' },
            { instructions: INSTRUCTIONS_TEMPLATE_V1 }
        )
    }

    get requestProperties(): RequestProperties {
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

    async detectRegion(): Promise<CloudRegion | undefined> {
        const usClient = new ApiClient({
            apiToken: this.props.apiToken,
            baseUrl: POSTHOG_US_BASE_URL,
        })

        const euClient = new ApiClient({
            apiToken: this.props.apiToken,
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
        const customApiBaseUrl = getCustomApiBaseUrl()
        if (customApiBaseUrl) {
            return customApiBaseUrl
        }

        // Check region from request props first (passed via URL param), then cache, then detect
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

            const client = getPostHogClient()

            await this.resolveClientInfo()

            const clientName = await this.cache.get('clientName')

            const contextProperties = options?.context ? buildMCPContextProperties(options.context) : {}
            const previousContextProperties = options?.previousContext
                ? buildMCPContextProperties(options.previousContext, { prefix: 'previous_' })
                : {}
            const groups = options?.context ? buildMCPAnalyticsGroups(options.context) : {}

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
                    void this.trackContextSwitchEvent(tool.name, await this.getContext(), previousContext)
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
                    this.props.sessionId
                        ? await this.sessionManager.getSessionUuid(this.props.sessionId)
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
        } = this.props

        // Resolve MCP client info before any code reads it
        await this.resolveClientInfo()

        const clientProfile = new MCPClientProfile({
            clientName: this.mcpClientName,
            clientVersion: this.mcpClientVersion,
            consumer: this.props.mcpConsumer,
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
        // userHash already picked a project (cache survives across requests).
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

        // Restrict single-exec mode to coding agents only
        const useSingleExec =
            mode === 'cli' ||
            (mode !== 'tools' &&
                singleExecFlagOn &&
                (clientProfile.isCodingAgent() || clientProfile.isPostHogCodeConsumer()))
        const version = useSingleExec ? 2 : (flagVersion ?? clientVersion ?? 1)

        // Fetch group types and metadata in parallel (cache is now seeded)
        const resolvedProjectId = projectId || (await this.cache.get('projectId'))
        const [groupTypes, metadata] = await Promise.all([
            resolvedProjectId
                ? context.stateManager.getOrFetchGroupTypes(resolvedProjectId)
                : Promise.resolve(undefined),
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

        let instructions = ''
        if (supportsInstructions) {
            if (useSingleExec) {
                instructions = buildInstructionsV2(
                    SINGLE_EXEC_INSTRUCTIONS,
                    _guidelines,
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
                              _guidelines,
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

        // In single-exec mode, register one "posthog" tool that wraps all tools
        // behind a CLI-like interface. Otherwise, register each tool individually.
        if (useSingleExec) {
            const sqlTool = allTools.find((t) => t.name === 'execute-sql')
            if (sqlTool) {
                sqlTool.description = formatPrompt(EXECUTE_SQL_PROMPT, { guidelines: _guidelines.trim() })
            }

            const commandReference = buildInstructionsV2(
                CLI_PROXY_COMMAND,
                _guidelines,
                supportsInstructions ? undefined : groupTypes,
                supportsInstructions ? undefined : metadata,
                supportsInstructions ? undefined : toolInfos,
                supportsInstructions ? undefined : queryToolInfos
            )

            const trackInnerCall: ExecInnerCallTracker = (toolName, properties) => {
                void (async () => {
                    const freshContext = await this.getAnalyticsContextSafe(await this.getContext())
                    await this.trackEvent(
                        AnalyticsEvent.MCP_TOOL_CALLED,
                        { tool_name: toolName, ...properties },
                        freshContext ? { context: freshContext } : undefined
                    )
                })()
            }

            const execTool = createExecTool(
                allTools,
                context,
                CLI_PROXY_TOOL,
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

        await initMcpCatObservability(this.server, {
            getDistinctId: () => this.getDistinctId(),
            getSessionUuid: async () =>
                this.props.sessionId
                    ? this.sessionManager.getSessionUuid(this.props.sessionId)
                    : undefined,
            getMcpClientName: async () => this.mcpClientName,
            getMcpClientVersion: async () => this.mcpClientVersion,
            getMcpProtocolVersion: async () => this.mcpProtocolVersion,
            // Prefer the cached region (set on init after detection) so we don't miss it
            // when the inbound request didn't include the `region` hint.
            getRegion: async () => (await this.cache.get('region')) ?? this.props.region,
            getAnalyticsContext: async () => this.getAnalyticsContextSafe(await this.getContext()),
            getClientUserAgent: async () => this.props.clientUserAgent,
            getVersion: async () => version,
            getOAuthClientName: async () => (await this.cache.get('clientName')) || undefined,
            getReadOnly: async () => readOnly,
            getTransport: async () => this.props.transport,
        })

        const initDurationMs = this.props.requestStartTime
            ? Date.now() - this.props.requestStartTime
            : undefined

        // Resolve analytics context from the already-primed cache
        const analyticsContext = await this.getAnalyticsContextSafe(context)

        void this.trackEvent(
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
