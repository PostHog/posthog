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
    /**
     * Output format for the tool response. `'optimized'` surfaces the backend formatter output
     * (`formatted_results`) as the text content when available; `'json'` skips the formatter
     * override entirely and returns raw JSON. Omit to fall back to the default TOON encoding.
     */
    outputFormat?: 'optimized' | 'json'
    /** When set, `_posthogUrl` uses `{baseUrl}{urlPrefix}` instead of `/insights/new#q=...`. */
    urlPrefix?: string
    /** When set, the tool is only available in this MCP version (1 = v1 only, 2 = v2 only). */
    mcpVersion?: number
}

function buildInsightUrl(
    kind: 'InsightVizNode' | 'DataTableNode',
    query: Record<string, unknown>,
    baseUrl: string,
    urlPrefix?: string
): string {
    if (urlPrefix) {
        return `${baseUrl}${urlPrefix}`
    }
    const q = encodeURIComponent(JSON.stringify({ kind, source: query }))
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
            // `output_format` is a tool-level control, not part of the query body. Strip it before
            // POSTing so it doesn't leak into the backend `kind: ...Query` payload.
            const { output_format: callerOutputFormat, ...queryParams } = params as typeof params & {
                output_format?: 'optimized' | 'json'
            }
            const query: Record<string, unknown> = { ...queryParams, kind: config.kind }
            const baseUrl = context.api.getProjectBaseUrl(projectId)
            const effectiveOutputFormat = callerOutputFormat ?? config.outputFormat

            if (config.kind.endsWith('ActorsQuery')) {
                const sourceKind = (query.source as Record<string, unknown> | undefined)?.kind
                const queryClient = context.api.query({ projectId })
                let data
                switch (sourceKind) {
                    case 'LifecycleQuery':
                        data = await queryClient.lifecycleActors({ query })
                        break
                    case 'TrendsQuery':
                        data = await queryClient.trendsActors({ query })
                        break
                    default:
                        throw new Error(`Unsupported source kind for actors query: ${sourceKind}`)
                }
                return {
                    ...data,
                    _posthogUrl: buildInsightUrl('DataTableNode', data.query, baseUrl, config.urlPrefix),
                }
            }

            const data = await context.api.query({ projectId }).runQuery({ query })
            const shouldSurfaceFormatted = effectiveOutputFormat !== 'json' && data.formatted_results
            // Include `query` in the payload so UI apps (TrendsVisualizer, LifecycleVisualizer)
            // can honor query-level filters like `lifecycleFilter.toggledLifecycles` and
            // `trendsFilter.display`. `timezone` from the cached response drives interval-aware
            // x-axis formatting in the line chart.
            return {
                query,
                results: data.results,
                ...(data.timezone ? { timezone: data.timezone } : {}),
                _posthogUrl: buildInsightUrl('InsightVizNode', query, baseUrl, config.urlPrefix),
                ...(shouldSurfaceFormatted ? { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: data.formatted_results } : {}),
            }
        },
        _meta: {
            ...(config.uiResourceUri ? { ui: { resourceUri: config.uiResourceUri } } : {}),
            ...(config.outputFormat ? { [POSTHOG_META_KEY]: { outputFormat: config.outputFormat } } : {}),
        },
    })
}
