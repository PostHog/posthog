import { z } from 'zod'

import {
    POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY,
    POSTHOG_META_KEY,
    type Context,
    type ToolBase,
    type ZodObjectAny,
} from '@/tools/types'

interface QueryWrapperConfig<T extends ZodObjectAny> {
    name: string
    schema: T
    kind: string
    uiResourceUri?: string
    /** Return JSON instead of TOON-encoded text. */
    responseFormat?: 'json'
    /** When set, `_posthogUrl` uses `{baseUrl}{urlPrefix}` instead of `/insights/new#q=...`. */
    urlPrefix?: string
    /** When set, the tool is only available in this MCP version (1 = v1 only, 2 = v2 only). */
    mcpVersion?: number
}

function buildInsightUrl(baseUrl: string, urlPrefix: string | undefined, query: Record<string, unknown>): string {
    if (urlPrefix) {
        return `${baseUrl}${urlPrefix}`
    }
    const q = encodeURIComponent(JSON.stringify({ kind: 'InsightVizNode', source: query }))
    return `${baseUrl}/insights/new#q=${q}`
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
            const baseUrl = context.api.getProjectBaseUrl(projectId)

            if (config.kind.endsWith('ActorsQuery')) {
                const data = await context.api.query({ projectId }).trendsActors({ query })
                return {
                    ...data,
                    // TODO: _posthogUrl
                }
            }

            const data = await context.api.query({ projectId }).runQuery({ query })
            return {
                results: data.results,
                _posthogUrl: buildInsightUrl(baseUrl, config.urlPrefix, query),
                ...(data.formatted_results ? { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: data.formatted_results } : {}),
            }
        },
        _meta: {
            ...(config.uiResourceUri ? { ui: { resourceUri: config.uiResourceUri } } : {}),
            ...(config.responseFormat ? { [POSTHOG_META_KEY]: { responseFormat: config.responseFormat } } : {}),
        },
    })
}
