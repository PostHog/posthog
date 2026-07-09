import type { GroupType } from '@/api/client'
import { hasScope } from '@/lib/api'
import { MCPClientProfile } from '@/lib/client-detection'
import { isLocalApi } from '@/lib/constants'
import { buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import {
    type EvaluatedFlags,
    evaluateFeatureFlags,
    type FlagGroups,
    resolveFeatureFlagOverrides,
} from '@/lib/posthog/flags'
import type { RequestProperties } from '@/lib/request-properties'
import type { McpMode } from '@/lib/utils'
import { SQL_SCHEMA_DISCOVERY_FEATURE_FLAG } from '@/tools/posthogAiTools/readDataWarehouseSchema'
import { RENDER_UI_FEATURE_FLAG } from '@/tools/render-ui'
import { getRequiredFeatureFlags, getScopeGatedTools, type ScopeGatedTool } from '@/tools/toolDefinitions'
import type { Context, Tool, Env, State, ZodObjectAny } from '@/tools/types'

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
    clientProfile: MCPClientProfile
    requestContext: MCPRequestContext
    sessionContext: MCPSessionContext | null
    allTools: Tool<ZodObjectAny>[]
    scopeGatedTools: ScopeGatedTool[]
    distinctId: string
    renderUiEnabled: boolean
    // Active project/user environment prompt and group types. Rendered into the
    // `instructions` payload, and (for clients that don't surface instructions to
    // the model like Codex, or ignore it like Claude web/desktop) the exec command
    // reference. Resolved once here so every render path reads the same source.
    metadata: string | undefined
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

// ─── Resolver ───

const SESSION_CONTEXT_KEYS = [
    'mcpClientName',
    'mcpClientVersion',
    'mcpProtocolVersion',
    'mcpConsumer',
    'mcpVendorClient',
] as const
type SessionContextKey = (typeof SESSION_CONTEXT_KEYS)[number]
type SessionContextCache = Pick<State, SessionContextKey>

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
        const sessionContext = await this.resolveSessionContext(reqCtx, requestContext)
        const clientContext = getEffectiveMCPClientContext(requestContext, sessionContext)

        const context = await reqCtx.getContext()

        const { features, tools, organizationId, projectId, readOnly } = props

        await reqCtx.tokenCache.setMany({
            ...(organizationId ? { orgId: organizationId } : {}),
            ...(projectId ? { projectId } : {}),
        })

        let cachedProjectId = projectId || (await reqCtx.tokenCache.get('projectId'))
        if (!cachedProjectId) {
            await context.stateManager.setDefaultOrganizationAndProject()
            cachedProjectId = (await reqCtx.tokenCache.get('projectId')) ?? undefined
        }

        const toolFlagKeys = getRequiredFeatureFlags()
        // `mcp-render-ui` isn't a catalog tool flag, but it rides the same batched
        // evaluation and lives in the same map so the instructions layer can gate
        // the rendering prompt section on it (like `mcp-feedback-tool`).
        // `mcp-sql-schema-discovery` now gates the read-data-warehouse-schema tool, so
        // it already arrives via `getRequiredFeatureFlags()`; keep it listed (and dedupe)
        // since the instructions layer also reads it for SQL discovery steering — neither
        // concern should depend on the other's wiring.
        const allFlagKeys = [...new Set([...toolFlagKeys, RENDER_UI_FEATURE_FLAG, SQL_SCHEMA_DISCOVERY_FEATURE_FLAG])]

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
        const renderUiFlagEnabled = mergedFlags[RENDER_UI_FEATURE_FLAG] === true

        const oauthClientName = (await reqCtx.tokenCache.get('clientName')) || undefined

        const clientProfile = new MCPClientProfile({
            clientName: clientContext.mcpClientName,
            clientVersion: clientContext.mcpClientVersion,
            consumer: clientContext.mcpConsumer,
            oauthClientName,
            vendorClient: clientContext.mcpVendorClient,
            userAgent: props.clientUserAgent,
        })

        // `render-ui` is only meaningful for MCP Apps hosts (Claude web/desktop) that can
        // mount its iframe. The flag is necessary but not sufficient: Claude Code and other
        // single-exec CLI clients pool the same flag value, so the tool's advertisement and
        // execution must also require the UI-host check — otherwise rolling the flag out to
        // everyone leaks `render-ui` into Claude Code.
        const renderUiEnabled = renderUiFlagEnabled && clientProfile.isClaudeUiHost()

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

        const excludeTools: string[] = []
        if (projectId) {
            excludeTools.push('switch-organization', 'switch-project')
        } else if (organizationId) {
            excludeTools.push('switch-organization')
        }

        const filterOptions = {
            features,
            tools,
            excludeTools,
            readOnly,
            featureFlags: toolFeatureFlags,
            scopedTeams: apiKeyScopedTeams,
            aiConsentGiven: aiConsentGiven ?? undefined,
        }
        const allTools = this.catalog.getFilteredTools({ ...filterOptions, scopes: apiKeyScopes })
        // Scope-gated hints are only consumed by the exec `search` command, which
        // only exists in single-exec mode — skip the extra scan otherwise.
        const scopeGatedTools = useSingleExec ? getScopeGatedTools(apiKeyScopes, filterOptions) : []

        const [groupTypes, metadata] = await Promise.all([
            cachedProjectId && hasScope(apiKeyScopes, 'group:read')
                ? context.stateManager.getOrFetchGroupTypes(cachedProjectId).catch(() => undefined)
                : undefined,
            context.stateManager.getEnvironmentPrompt(),
        ])

        return {
            reqCtx,
            context,
            useSingleExec,
            toolFeatureFlags,
            apiKeyScopes,
            clientProfile,
            requestContext,
            sessionContext,
            allTools,
            scopeGatedTools,
            distinctId,
            renderUiEnabled,
            metadata,
            groupTypes,
        }
    }

    private async resolveSessionContext(
        reqCtx: RequestContext,
        requestContext: MCPRequestContext
    ): Promise<MCPSessionContext | null> {
        if (!requestContext.mcpSessionId) {
            return null
        }

        const cachedEntries = await Promise.all(
            SESSION_CONTEXT_KEYS.map(async (key) => [key, await reqCtx.sessionCache.get(key)] as const)
        )
        const cachedContext = Object.fromEntries(cachedEntries) as Partial<SessionContextCache>

        const cacheUpdates: Partial<SessionContextCache> = {}
        for (const key of SESSION_CONTEXT_KEYS) {
            if (!cachedContext[key] && requestContext[key]) {
                cacheUpdates[key] = requestContext[key]
            }
        }

        if (Object.keys(cacheUpdates).length > 0) {
            await reqCtx.sessionCache.setMany(cacheUpdates)
        }

        return Object.fromEntries(
            SESSION_CONTEXT_KEYS.map((key) => [key, cachedContext[key] || requestContext[key] || undefined])
        ) as MCPSessionContext
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
        // surfaces these flags gate (e.g. the agent-platform product DB) exist.
        // The flags only hide those surfaces on prod until GA, so enable them all
        // locally — the analytics flag-eval client is disabled in dev anyway.
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
