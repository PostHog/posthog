import { z } from 'zod'

import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

import { resolveStrategy, type QueryResponse } from './query-wrapper/strategies'

interface QueryWrapperConfig<T extends ZodObjectAny> {
    name: string
    schema: T
    kind: string
    uiResourceUri?: string
    /** Return JSON instead of TOON-encoded text. */
    responseFormat?: 'json'
    /** When set, `_posthogUrl` uses `{baseUrl}{urlPrefix}` instead of `/insights/new?q=...`. */
    urlPrefix?: string
    /** When set, the tool is only available in this MCP version (1 = v1 only, 2 = v2 only). */
    mcpVersion?: number
}

// Convert flat filterGroup arrays (from assistant schemas) into the nested
// PropertyGroupFilter structure the query API expects.
function normalizeFilterGroup(query: Record<string, unknown>): void {
    if (!Array.isArray(query.filterGroup)) {
        return
    }
    if (query.filterGroup.length > 0) {
        query.filterGroup = {
            type: 'AND',
            values: [{ type: 'AND', values: query.filterGroup }],
        }
    } else {
        delete query.filterGroup
    }
}

export function createQueryWrapper<T extends ZodObjectAny>(config: QueryWrapperConfig<T>): () => ToolBase<T> {
    return () => ({
        name: config.name,
        schema: config.schema,
        ...(config.mcpVersion !== undefined ? { mcpVersion: config.mcpVersion } : {}),
        handler: async (context: Context, rawParams: z.infer<T>) => {
            const projectId = await context.stateManager.getProjectId()
            const params = config.schema.parse(rawParams)
            const query: Record<string, unknown> = { ...params, kind: config.kind }
            normalizeFilterGroup(query)

            const strategy = resolveStrategy(config.kind)
            const formattedQuery = strategy.formatRequest(query)
            const response = await context.api.request<QueryResponse>({
                method: 'POST',
                path: `/api/environments/${projectId}/query/`,
                body: { query: formattedQuery },
            })

            const baseUrl = context.api.getProjectBaseUrl(projectId)
            return strategy.formatResponse(response, formattedQuery, baseUrl, config.urlPrefix)
        },
        _meta: {
            ...(config.uiResourceUri ? { ui: { resourceUri: config.uiResourceUri } } : {}),
            ...(config.responseFormat ? { responseFormat: config.responseFormat } : {}),
        },
    })
}
