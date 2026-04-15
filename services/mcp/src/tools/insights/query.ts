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

export const queryHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const { insightId, format } = params
    const projectId = await context.stateManager.getProjectId()

    const insightResult = await context.api.insights({ projectId }).get({ insightId })

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

    // Use server-side formatted results when format is 'optimized' and available
    const useFormatted = format === 'optimized' && queryResult.data.formatted_results != null

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
