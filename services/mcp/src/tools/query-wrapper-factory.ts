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
}

const TEST_ACCOUNT_FILTER_FIELD = 'filterTestAccounts'

function hasTestAccountFilterField(schema: ZodObjectAny): schema is z.ZodObject<z.ZodRawShape> {
    return schema instanceof z.ZodObject && TEST_ACCOUNT_FILTER_FIELD in schema.shape
}

/**
 * Most generated query schemas hard-default `filterTestAccounts` to `false`, which
 * silently ignores the project's "Filter out internal and test users" default
 * (`test_account_filters_default_checked`) that the UI applies to every new
 * insight. Stripping the schema default lets an omitted value survive validation
 * as `undefined`, so the handler can fill in the project default instead. An
 * explicit `filterTestAccounts` from the caller always wins.
 *
 * Only a `false` default is stripped: a schema that defaults the field to `true`
 * (e.g. AssistantTracesQuery) is an intentional stricter product default, and
 * replacing it would flip its queries to unfiltered on projects where the
 * setting is unchecked.
 */
function withoutTestAccountFilterDefault<T extends ZodObjectAny>(schema: T): T {
    if (!hasTestAccountFilterField(schema)) {
        return schema
    }
    // `ZodRawShape` values are typed as core `$ZodType`, which hides `safeParse`.
    const field = schema.shape[TEST_ACCOUNT_FILTER_FIELD] as z.ZodType
    const omittedValue = field.safeParse(undefined)
    if (!omittedValue.success || omittedValue.data !== false) {
        return schema
    }
    return schema.extend({
        // Strict boolean, not `z.coerce.boolean()`: coercion turns the string
        // `"false"` into `true`, which would silently flip query semantics.
        [TEST_ACCOUNT_FILTER_FIELD]: z
            .boolean()
            .optional()
            .describe(
                'Exclude internal and test users by applying the respective filters. When omitted, follows the project\'s "Filter out internal and test users" default setting.'
            ),
    }) as unknown as T
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
    // Both the advertised tool schema and the handler's re-parse must use the
    // stripped schema — parsing with the original would re-apply the `false`
    // default and make omission indistinguishable from an explicit `false`.
    const schema = withoutTestAccountFilterDefault(config.schema)
    return () => ({
        name: config.name,
        schema,
        handler: async (context: Context, rawParams: z.infer<T>) => {
            const projectId = await context.stateManager.getProjectId()
            const params = schema.parse(rawParams)
            // `output_format` is a tool-level control, not part of the query body. Strip it before
            // POSTing so it doesn't leak into the backend `kind: ...Query` payload.
            const { output_format: callerOutputFormat, ...queryParams } = params as typeof params & {
                output_format?: 'optimized' | 'json'
            }
            const query: Record<string, unknown> = {
                ...queryParams,
                kind: config.kind,
            }
            if (hasTestAccountFilterField(schema) && query[TEST_ACCOUNT_FILTER_FIELD] === undefined) {
                const project = await context.stateManager.getCachedOrFetchProject().catch(() => undefined)
                // Only inject `true`: when the project default is unchecked the field
                // stays omitted and the backend's own `false` default applies.
                if (project?.test_account_filters_default_checked) {
                    query[TEST_ACCOUNT_FILTER_FIELD] = true
                }
            }
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
                    case 'PathsQuery':
                        data = await queryClient.pathsActors({ query })
                        break
                    case 'RetentionQuery':
                        data = await queryClient.retentionActors({ query })
                        break
                    case 'StickinessQuery':
                        data = await queryClient.stickinessActors({ query })
                        break
                    case 'FunnelsQuery':
                        data = await queryClient.funnelActors({ query })
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
            // `trendsFilter.display`.
            return {
                query,
                results: data.results,
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
