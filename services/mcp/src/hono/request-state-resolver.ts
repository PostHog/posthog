import { MCPClientProfile } from '@/lib/client-detection'
import { buildMCPAnalyticsGroups } from '@/lib/posthog/analytics'
import { evaluateFeatureFlags, type FlagGroups } from '@/lib/posthog/flags'
import type { RequestProperties } from '@/lib/request-properties'
import type { McpMode } from '@/lib/utils'
import { getRequiredFeatureFlags } from '@/tools/toolDefinitions'
import type { Context, Tool, Env, ZodObjectAny } from '@/tools/types'

import type { RedisLike } from './cache/RedisCache'
import { RequestContext } from './request-context'
import type { ToolCatalog } from './tool-catalog'

// ─── Per-request resolved state ───

export interface ResolvedState {
    reqCtx: RequestContext
    context: Context
    version: number
    useSingleExec: boolean
    toolFeatureFlags: Record<string, boolean> | undefined
    apiKeyScopes: string[]
    clientProfile: MCPClientProfile
    allTools: Tool<ZodObjectAny>[]
    distinctId: string
}

// ─── Pure helpers ───

export function resolveModeAndVersion(args: {
    mode: McpMode | undefined
    singleExecFlagOn: boolean
    clientProfile: MCPClientProfile
}): { useSingleExec: boolean; version: number } {
    const { mode, singleExecFlagOn, clientProfile } = args
    const useSingleExec =
        mode === 'cli' ||
        (mode !== 'tools' &&
            singleExecFlagOn &&
            (clientProfile.isCodingAgent() ||
                clientProfile.isPostHogCodeConsumer() ||
                clientProfile.isVibeCodingClient()))
    return { useSingleExec, version: 2 }
}

// ─── Resolver ───

const SYSTEM_FLAGS = ['mcp-single-exec-tool'] as const

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
        const reqCtx = new RequestContext(this.redis, this.env, props)
        const context = await reqCtx.getContext()

        const { features, tools, organizationId, projectId, readOnly, mode } = props

        await reqCtx.cache.setMany({
            ...(organizationId ? { orgId: organizationId } : {}),
            ...(projectId ? { projectId } : {}),
            ...(props.mcpClientName ? { mcpClientName: props.mcpClientName } : {}),
            ...(props.mcpClientVersion ? { mcpClientVersion: props.mcpClientVersion } : {}),
            ...(props.mcpProtocolVersion ? { mcpProtocolVersion: props.mcpProtocolVersion } : {}),
        })

        let cachedProjectId = projectId || (await reqCtx.cache.get('projectId'))
        if (!cachedProjectId) {
            await context.stateManager.setDefaultOrganizationAndProject()
            cachedProjectId = (await reqCtx.cache.get('projectId')) ?? undefined
        }

        const toolFlagKeys = getRequiredFeatureFlags()
        const allFlagKeys = [...SYSTEM_FLAGS, ...toolFlagKeys]

        const flagAnalyticsContext = await reqCtx.getAnalyticsContextSafe(context)
        const flagGroups = flagAnalyticsContext ? buildMCPAnalyticsGroups(flagAnalyticsContext) : undefined

        const [allFlags, _apiKey, distinctId] = await Promise.all([
            this.resolveAllFlags(reqCtx, allFlagKeys, flagGroups),
            context.stateManager.getApiKey(),
            reqCtx.getDistinctId(),
        ])

        const singleExecFlagOn = !!allFlags['mcp-single-exec-tool']
        const toolFeatureFlags = toolFlagKeys.length > 0
            ? Object.fromEntries(toolFlagKeys.map((k) => [k, !!allFlags[k]]))
            : undefined

        const oauthClientName = (await reqCtx.cache.get('clientName')) || undefined
        const mcpClientName = props.mcpClientName || (await reqCtx.cache.get('mcpClientName')) || undefined
        const mcpClientVersion = props.mcpClientVersion || (await reqCtx.cache.get('mcpClientVersion')) || undefined
        const clientProfile = new MCPClientProfile({
            clientName: mcpClientName,
            clientVersion: mcpClientVersion,
            consumer: props.mcpConsumer,
            oauthClientName,
        })

        const { useSingleExec, version } = resolveModeAndVersion({
            mode,
            singleExecFlagOn,
            clientProfile,
        })

        const apiKeyScopes = _apiKey?.scopes ?? []
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
            aiConsentGiven: aiConsentGiven ?? undefined,
        })

        return {
            reqCtx,
            context,
            version,
            useSingleExec,
            toolFeatureFlags,
            apiKeyScopes,
            clientProfile,
            allTools,
            distinctId,
        }
    }

    private async resolveAllFlags(
        reqCtx: RequestContext,
        flagKeys: string[],
        groups?: FlagGroups
    ): Promise<Record<string, boolean>> {
        if (flagKeys.length === 0) {return {}}
        try {
            const distinctId = await reqCtx.getDistinctId()
            return await evaluateFeatureFlags(flagKeys, distinctId, groups)
        } catch {
            return {}
        }
    }
}
