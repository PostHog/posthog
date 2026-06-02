import { MCPClientProfile } from '@/lib/client-detection'
import { buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import { type EvaluatedFlags, evaluateFeatureFlags, type FlagGroups } from '@/lib/posthog/flags'
import type { RequestProperties } from '@/lib/request-properties'
import type { McpMode } from '@/lib/utils'
import { getRequiredFeatureFlags } from '@/tools/toolDefinitions'
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
    distinctId: string
}

// ─── Pure helpers ───

export function resolveMode(args: { mode: McpMode | undefined; clientProfile: MCPClientProfile }): {
    mode: McpMode
    useSingleExec: boolean
} {
    const { mode, clientProfile } = args
    const useSingleExec =
        mode === 'cli' ||
        (mode !== 'tools' &&
            (clientProfile.isCodingAgent() ||
                clientProfile.isPostHogCodeConsumer() ||
                clientProfile.isVibeCodingClient()))
    return { mode: mode ?? (useSingleExec ? 'cli' : 'tools'), useSingleExec }
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
        const allFlagKeys = toolFlagKeys

        const flagAnalyticsContext = await reqCtx.getAnalyticsContextSafe(context)
        const flagGroups = flagAnalyticsContext ? buildMCPAnalyticsGroups(flagAnalyticsContext) : undefined

        const [allFlags, _apiKey, distinctId] = await Promise.all([
            this.resolveAllFlags(reqCtx, allFlagKeys, flagGroups),
            context.stateManager.getApiKey(),
            reqCtx.getDistinctId(),
        ])

        // Preserve variant strings (and `undefined` for unevaluated flags) — the
        // tool filter needs raw values to support `feature_flag_variant` matching.
        const toolFeatureFlags =
            toolFlagKeys.length > 0 ? Object.fromEntries(toolFlagKeys.map((k) => [k, allFlags[k]])) : undefined

        const oauthClientName = (await reqCtx.tokenCache.get('clientName')) || undefined

        const clientProfile = new MCPClientProfile({
            clientName: clientContext.mcpClientName,
            clientVersion: clientContext.mcpClientVersion,
            consumer: clientContext.mcpConsumer,
            oauthClientName,
            vendorClient: clientContext.mcpVendorClient,
        })

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

        const allTools = this.catalog.getFilteredTools({
            features,
            tools,
            excludeTools,
            readOnly,
            featureFlags: toolFeatureFlags,
            scopes: apiKeyScopes,
            scopedTeams: apiKeyScopedTeams,
            aiConsentGiven: aiConsentGiven ?? undefined,
        })

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
            distinctId,
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
        try {
            const distinctId = await reqCtx.getDistinctId()
            return await evaluateFeatureFlags(flagKeys, distinctId, groups)
        } catch {
            return {}
        }
    }
}
