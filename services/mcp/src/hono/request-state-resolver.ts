import { MCPClientProfile } from '@/lib/client-detection'
import type { RequestProperties } from '@/lib/request-properties'
import type { Env } from '@/tools/types'

import type { RedisLike } from './cache/RedisCache'
import { type ResolvedState, resolveModeAndVersion } from './protocol-types'
import { RequestContext } from './request-context'
import type { ToolCatalog } from './tool-catalog'

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

        if (organizationId) await reqCtx.cache.set('orgId', organizationId)
        if (projectId) await reqCtx.cache.set('projectId', projectId)

        let cachedProjectId = projectId || (await reqCtx.cache.get('projectId'))
        if (!cachedProjectId) {
            await context.stateManager.setDefaultOrganizationAndProject()
            cachedProjectId = (await reqCtx.cache.get('projectId')) ?? undefined
        }

        const [flagVersion, toolFeatureFlags, singleExecFlagOn, _apiKey, distinctId] = await Promise.all([
            reqCtx.resolveVersionFlag(),
            reqCtx.resolveToolFeatureFlags(clientVersion),
            reqCtx.resolveSingleExecFlag(),
            context.stateManager.getApiKey(),
            reqCtx.getDistinctId(),
        ])

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
}
