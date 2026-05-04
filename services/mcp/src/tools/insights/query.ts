import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import type { Insight } from '@/schema/insights'
import { InsightQueryInputSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { analyzeQuery } from '../shared'

const schema = InsightQueryInputSchema

type Params = z.infer<typeof schema>

type Result = WithPostHogUrl<{ query: unknown; insight: Insight & { url: string }; results: unknown }>

// Accept either a pre-encoded JSON string or a plain object for the override
// params. LLM agents reading the insight-get response see `variables` as an
// object, so requiring them to JSON.stringify before sending is friction that
// frequently breaks (escaping, double-encoding). Normalising here lets either
// shape reach the backend as a properly-encoded query-string value.
//
// Transitional: the auto-generated tools rely on ApiClient.request() in
// services/mcp/src/api/client.ts, which already JSON-stringify-s object query
// params automatically. This helper exists because the bespoke insights().get()
// in client.ts builds its own URLSearchParams and types the override params as
// `string`. Once that endpoint migrates onto request(), normalizeOverride can
// be deleted.
function normalizeOverride(value: string | Record<string, unknown> | undefined): string | undefined {
    if (value === undefined) {
        return undefined
    }
    return typeof value === 'string' ? value : JSON.stringify(value)
}

export const queryHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const { insightId, output_format, variables_override, filters_override } = params
    const projectId = await context.stateManager.getProjectId()

    // Threading overrides through the .get() call lets the Django retrieve endpoint
    // merge them server-side (via apply_dashboard_variables_to_dict /
    // apply_dashboard_filters_to_dict). The merged query is then POSTed to /query/
    // as-is, so insight-query results reflect the overridden values without
    // mutating the saved insight.
    const insightResult = await context.api.insights({ projectId }).get({
        insightId,
        variables_override: normalizeOverride(variables_override),
        filters_override: normalizeOverride(filters_override),
    })

    if (!insightResult.success) {
        throw new Error(`Failed to get insight: ${insightResult.error.message}`)
    }

    const queryResult = await context.api.insights({ projectId }).query({
        query: insightResult.data.query,
    })

    if (!queryResult.success) {
        throw new Error(`Failed to query insight: ${queryResult.error.message}`)
    }

    const path = `/insights/${insightResult.data.short_id}`
    const queryInfo = analyzeQuery(insightResult.data.query)

    const useFormatted = output_format === 'optimized' && queryResult.data.formatted_results != null

    if (useFormatted) {
        return withPostHogUrl(
            context,
            {
                query: queryInfo.innerQuery || insightResult.data.query,
                insight: {
                    url: path,
                    ...insightResult.data,
                },
                results: queryResult.data.formatted_results,
            },
            path
        )
    }

    // JSON format or no formatter available — return raw results
    if (queryInfo.visualization === 'trends' || queryInfo.visualization === 'funnel') {
        return withPostHogUrl(
            context,
            {
                query: queryInfo.innerQuery || insightResult.data.query,
                insight: {
                    url: path,
                    ...insightResult.data,
                },
                results: queryResult.data.results,
            },
            path
        )
    }

    // HogQL/table results have columns and results arrays
    return withPostHogUrl(
        context,
        {
            query: insightResult.data.query,
            insight: {
                url: path,
                ...insightResult.data,
            },
            results: {
                columns: queryResult.data.columns || [],
                results: queryResult.data.results || [],
            },
        },
        path
    )
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('query-results', {
        name: 'insight-query',
        schema,
        handler: queryHandler,
    })
