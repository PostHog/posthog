import type { ListToolsResult } from '@modelcontextprotocol/sdk/types.js'

import { MCPClientProfile } from '@/lib/client-detection'
import { evaluateFeatureFlags } from '@/lib/posthog/flags'
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

// ─── Method handler callbacks (used by AnalyticsBridge ↔ Dispatcher) ───

export interface MethodHandlerCallbacks {
    handleInitialize(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<unknown>
    handleToolsList(state: ResolvedState, props: RequestProperties): Promise<ListToolsResult>
    handleToolCall(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<unknown>
}

// ─── Pure helpers ───

export function resolveModeAndVersion(args: {
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
    return { useSingleExec, version }
}

// ─── Resolver ───

const SYSTEM_FLAGS = ['mcp-version-2', 'mcp-single-exec-tool'] as const

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

        const { features, tools, version: clientVersion, organizationId, projectId, readOnly, mode } = props

        if (organizationId) {await reqCtx.cache.set('orgId', organizationId)}
        if (projectId) {await reqCtx.cache.set('projectId', projectId)}

        let cachedProjectId = projectId || (await reqCtx.cache.get('projectId'))
        if (!cachedProjectId) {
            await context.stateManager.setDefaultOrganizationAndProject()
            cachedProjectId = (await reqCtx.cache.get('projectId')) ?? undefined
        }

        const toolFlagKeys = getRequiredFeatureFlags(clientVersion)
        const allFlagKeys = [...SYSTEM_FLAGS, ...toolFlagKeys]

        const [allFlags, _apiKey, distinctId] = await Promise.all([
            this._resolveAllFlags(reqCtx, allFlagKeys),
            context.stateManager.getApiKey(),
            reqCtx.getDistinctId(),
        ])

        const flagVersion = allFlags['mcp-version-2'] ? 2 : undefined
        const singleExecFlagOn = !!allFlags['mcp-single-exec-tool']
        const toolFeatureFlags = toolFlagKeys.length > 0
            ? Object.fromEntries(toolFlagKeys.map((k) => [k, !!allFlags[k]]))
            : undefined

        const oauthClientName = (await reqCtx.cache.get('clientName')) || undefined
        const clientProfile = new MCPClientProfile({
            clientName: props.mcpClientName,
            clientVersion: props.mcpClientVersion,
            consumer: props.mcpConsumer,
            oauthClientName,
        })

        const { useSingleExec, version } = resolveModeAndVersion({
            mode,
            singleExecFlagOn,
            clientProfile,
            flagVersion,
            clientVersion,
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
            version,
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

    private async _resolveAllFlags(
        reqCtx: RequestContext,
        flagKeys: string[]
    ): Promise<Record<string, boolean>> {
        if (flagKeys.length === 0) {return {}}
        try {
            const distinctId = await reqCtx.getDistinctId()
            return await evaluateFeatureFlags(flagKeys, distinctId)
        } catch {
            return {}
        }
    }
}
