import type { GroupType } from '@/api/client'
import { hasScope } from '@/lib/api'
import { MCPClientProfile } from '@/lib/client-detection'
import { isCloudApi, isLocalApi, MCP_GATEWAY_FLAG } from '@/lib/constants'
import { buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import {
    type EvaluatedFlags,
    evaluateFeatureFlags,
    type FlagGroups,
    resolveFeatureFlagOverrides,
} from '@/lib/posthog/flags'
import type { RequestProperties } from '@/lib/request-properties'
import { filterStaffOnlyTools } from '@/lib/staff-only-tools'
import type { McpMode } from '@/lib/utils'
import { TASKS_CONTEXT_TOOL_NAMES } from '@/tools/tasksContext'
import { getRequiredFeatureFlags, getScopeGatedTools, type ScopeGatedTool } from '@/tools/toolDefinitions'
import type { Context, Tool, Env, ZodObjectAny } from '@/tools/types'

import { McpSessionRedisStore } from './cache/McpSessionRedisStore'
import type { RedisLike } from './cache/RedisCache'
import {
    buildMCPRequestContext,
    getEffectiveMCPClientContext,
    type MCPRequestContext,
    type MCPSessionContext,
} from './mcp-context'
import { RequestContext } from './request-context'
import type { ToolCatalog } from './tool-catalog'

// ─── Per-request resolved state ───

export interface ResolvedState {
    reqCtx: RequestContext
    context: Context
    useSingleExec: boolean
    toolFeatureFlags: EvaluatedFlags | undefined
    apiKeyScopes: string[]
    oauthClientId: string | undefined
    clientProfile: MCPClientProfile
    requestContext: MCPRequestContext
    sessionContext: MCPSessionContext | null
    allTools: Tool<ZodObjectAny>[]
    scopeGatedTools: ScopeGatedTool[]
    /**
     * Whether the caller's team may reach third-party MCP tools through `exec`.
     * Gated on the same flag as the gateway UI — the tools are the gateway's payoff,
     * so they roll out together. Also forced off in read-only mode: a connected
     * server's tools can mutate and PostHog can't prove otherwise, so the catalog's
     * read-only filter has no equivalent to apply to them.
     *
     * Deliberately not folded into `allTools`: `instructions.ts` looks every entry up in
     * the static tool-definition registry (which throws on an unknown name) and renders
     * the full roster into the instructions payload.
     */
    gatewayToolsEnabled: boolean
    distinctId: string
    renderUiEnabled: boolean
    // Active project/user environment prompt and group types. Rendered into the
    // `instructions` payload, and (for clients that don't surface instructions to
    // the model like Codex, or ignore it like Claude web/desktop) the exec command
    // reference. Resolved once here so every render path reads the same source.
    metadata: string | undefined
    // Variant of `metadata` without the product/integration context lines, for the
    // claude.ai exec command reference: that surface counts against the ~16 KiB
    // connector-registry cap on the serialized inputSchema, which already sits
    // within tens of characters of the worst-case env context. Every uncapped
    // surface renders the full `metadata`.
    metadataCompact: string | undefined
    groupTypes: GroupType[] | undefined
}

// ─── Pure helpers ───

export function resolveMode(args: { mode: McpMode | undefined; clientProfile: MCPClientProfile }): {
    mode: McpMode
    useSingleExec: boolean
} {
    const { mode, clientProfile } = args
    // CLI (single-exec) is the default; only allow-listed clients (Cursor,
    // ChatGPT) keep the full per-tool roster, and an explicit ?mode= /
    // x-posthog-mcp-mode header always wins over auto-detection.
    const resolved: McpMode = mode ?? (clientProfile.isToolsModeClient() ? 'tools' : 'cli')
    return { mode: resolved, useSingleExec: resolved === 'cli' }
}

export function tasksContextToolsToExclude(clientProfile: MCPClientProfile, taskId: string | undefined): string[] {
    return clientProfile.isPostHogCodeConsumer() && taskId ? [] : [...TASKS_CONTEXT_TOOL_NAMES]
}

/**
 * Which navigation switch tools to hide given the context the client explicitly
 * pinned via request params.
 *
 * Pinning fixes the *default* active context — it must not disable navigation.
 * Only an explicitly pinned organization is a hard lock: the client asked to
 * operate inside one org, so `switch-organization` is dropped while project
 * switching stays available. A pinned *project* excludes nothing, because the
 * documented cross-org flow depends on it: from an active project an agent
 * resolves an org via `organizations-get`, calls `switch-organization`, then
 * `switch-project` to reach a project in another organization (see the
 * `switch-project` tool description). Excluding the switch tools on a project
 * pin — which nearly every connection sends — made that flow impossible.
 *
 * Note this only affects keys that can act across orgs. A project-scoped key
 * (`scoped_teams`) never sees `switch-organization` regardless, because
 * `getToolsForFeatures` independently strips every `organization:*` tool the
 * backend would 403 for such a token.
 */
export function switchToolsToExclude(pinned: { organizationId?: string | undefined }): string[] {
    return pinned.organizationId ? ['switch-organization'] : []
}

// ─── Resolver ───

// Task origins whose sandbox mounts every shared gateway server as its own MCP server
// (`mcp__<server>__<tool>`). Surfacing the same tools through `exec` as `<slug>__<tool>` gives
// those agents a second, member-scoped name for each tool — one that resolves for a person
// running the task interactively and comes back empty for the service account the scheduled
// run uses, so instructions learned on one path silently fail on the other.
const DIRECT_GATEWAY_MOUNT_ORIGINS: ReadonlySet<string> = new Set(['signals_scout'])

function mountsGatewayServersDirectly(taskOriginProduct: string | undefined): boolean {
    return taskOriginProduct !== undefined && DIRECT_GATEWAY_MOUNT_ORIGINS.has(taskOriginProduct)
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
        const requestContext = buildMCPRequestContext(props)
        const reqCtx = new RequestContext(this.redis, this.env, props, requestContext)

        const { features, tools, organizationId, projectId, readOnly } = props
        const contextPromise = reqCtx.getContext()
        const pinnedSessionContextPromise = projectId ? this.resolveSessionContext(requestContext) : undefined

        await reqCtx.tokenCache.setMany({
            ...(organizationId ? { orgId: organizationId } : {}),
            ...(projectId ? { projectId } : {}),
        })

        let cachedProjectId = projectId || (await reqCtx.tokenCache.get('projectId'))
        if (!cachedProjectId) {
            const contextForDefault = await contextPromise
            await contextForDefault.stateManager.setDefaultOrganizationAndProject()
            cachedProjectId = (await reqCtx.tokenCache.get('projectId')) ?? undefined
        }

        const [context, sessionContext] = await Promise.all([
            contextPromise,
            pinnedSessionContextPromise ?? this.resolveSessionContext(requestContext),
        ])
        const clientContext = getEffectiveMCPClientContext(requestContext, sessionContext)

        // MCP_GATEWAY_FLAG gates no tool of its own — it gates the third-party tools `exec`
        // resolves — so the tool-definition scan can't discover it; join it in explicitly.
        const allFlagKeys = [...new Set([...getRequiredFeatureFlags(), MCP_GATEWAY_FLAG])]

        const flagAnalyticsContext = await reqCtx.safelyGetAnalyticsContext(context)
        const flagGroups = flagAnalyticsContext ? buildMCPAnalyticsGroups(flagAnalyticsContext) : undefined

        const [allFlags, _apiKey, distinctId] = await Promise.all([
            this.resolveAllFlags(reqCtx, allFlagKeys, flagGroups),
            context.stateManager.getApiKey(),
            reqCtx.getDistinctId(),
        ])

        // Dev/test-only overrides win over evaluated values (no-op in production).
        const overrides = resolveFeatureFlagOverrides(props.featureFlagOverrides)
        const mergedFlags = { ...allFlags, ...overrides }
        // Preserve variant strings (and `undefined` for unevaluated flags) — the
        // tool filter needs raw values to support `feature_flag_variant` matching.
        // Include override keys so a forced flag reaches the tool/instructions layer
        // even when no catalog tool referenced it.
        const flagKeysForState = [...new Set([...allFlagKeys, ...Object.keys(overrides)])]
        const toolFeatureFlags = Object.fromEntries(flagKeysForState.map((k) => [k, mergedFlags[k]]))

        const oauthClientName = (await reqCtx.tokenCache.get('clientName')) || undefined
        const oauthClientId = (await reqCtx.tokenCache.get('oauthClientId')) || undefined

        const clientProfile = new MCPClientProfile({
            clientName: clientContext.mcpClientName,
            clientVersion: clientContext.mcpClientVersion,
            consumer: clientContext.mcpConsumer,
            oauthClientName,
            vendorClient: clientContext.mcpVendorClient,
            userAgent: props.clientUserAgent,
        })

        // `render-ui` is only meaningful for MCP Apps hosts (Claude web/desktop) that can
        // mount its iframe. Single-exec CLI clients like Claude Code can't mount it, so the
        // tool's advertisement and execution stay gated on the UI-host check.
        const renderUiEnabled = clientProfile.isClaudeUiHost()

        const { mode: resolvedMode, useSingleExec } = resolveMode({
            mode: requestContext.mode,
            clientProfile,
        })
        requestContext.mode = resolvedMode
        reqCtx.setMcpContexts(requestContext, sessionContext)
        props.mode = resolvedMode

        const apiKeyScopes = _apiKey?.scopes ?? []
        const apiKeyScopedTeams = _apiKey?.scoped_teams ?? []
        const aiConsentGiven = await context.stateManager.getAiConsentGiven()
        const availableFeatures = await context.stateManager.getAvailableFeatures()
        const isCloud = isCloudApi()

        const excludeTools = [
            ...switchToolsToExclude({ organizationId }),
            ...tasksContextToolsToExclude(clientProfile, props.taskId),
        ]

        const filterOptions = {
            features,
            tools,
            excludeTools,
            readOnly,
            featureFlags: toolFeatureFlags,
            scopedTeams: apiKeyScopedTeams,
            aiConsentGiven: aiConsentGiven ?? undefined,
            availableFeatures,
            isCloud,
        }
        // Staff-only tools (OAuth-hidden scopes) need the extra explicit-scope +
        // is_staff gate on top of the catalog's plain scope filter.
        const allTools = await filterStaffOnlyTools(
            this.catalog.getFilteredTools({ ...filterOptions, scopes: apiKeyScopes }),
            _apiKey ?? { scopes: [] },
            () => context.stateManager.getUser()
        )
        // Scope-gated hints are only consumed by the exec `search` command, which
        // only exists in single-exec mode — skip the extra scan otherwise.
        const scopeGatedTools = useSingleExec ? getScopeGatedTools(apiKeyScopes, filterOptions) : []

        const [groupTypes, metadata, metadataCompact] = await Promise.all([
            cachedProjectId && hasScope(apiKeyScopes, 'group:read')
                ? context.stateManager.getOrFetchGroupTypes(cachedProjectId).catch(() => undefined)
                : undefined,
            context.stateManager.getEnvironmentPrompt(),
            context.stateManager.getEnvironmentPrompt({ includeProductContext: false }),
        ])

        return {
            reqCtx,
            context,
            useSingleExec,
            toolFeatureFlags,
            apiKeyScopes,
            oauthClientId,
            clientProfile,
            requestContext,
            sessionContext,
            allTools,
            scopeGatedTools,
            gatewayToolsEnabled:
                useSingleExec &&
                !readOnly &&
                mergedFlags[MCP_GATEWAY_FLAG] === true &&
                !mountsGatewayServersDirectly(props.taskOriginProduct),
            distinctId,
            renderUiEnabled,
            metadata,
            metadataCompact,
            groupTypes,
        }
    }

    private async resolveSessionContext(requestContext: MCPRequestContext): Promise<MCPSessionContext | null> {
        if (!requestContext.mcpSessionId) {
            return null
        }
        return new McpSessionRedisStore(this.redis, requestContext.mcpSessionId).resolve(requestContext)
    }

    private async resolveAllFlags(
        reqCtx: RequestContext,
        flagKeys: string[],
        groups?: FlagGroups
    ): Promise<EvaluatedFlags> {
        if (flagKeys.length === 0) {
            return {}
        }
        // Local dev runs against the locally-running project, where the dev-only
        // surfaces these flags gate exist. The flags only hide those surfaces on
        // prod until GA, so enable them all locally — the analytics flag-eval client is disabled in dev anyway.
        if (isLocalApi()) {
            return Object.fromEntries(flagKeys.map((key) => [key, true]))
        }
        try {
            const distinctId = await reqCtx.getDistinctId()
            return await evaluateFeatureFlags(flagKeys, distinctId, groups)
        } catch {
            return {}
        }
    }
}
