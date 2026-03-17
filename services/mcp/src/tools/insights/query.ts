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
    const { insightId } = params
    const projectId = await context.stateManager.getProjectId()

    const insightResult = await context.api.insights({ projectId }).get({ insightId })

    if (!insightResult.success) {
        throw new Error(`Failed to get insight: ${insightResult.error.message}`)
    }

    // Query the insight with parameters to get actual results
    const queryResult = await context.api.insights({ projectId }).query({
        query: insightResult.data.query,
    })

    if (!queryResult.success) {
        throw new Error(`Failed to query insight: ${queryResult.error.message}`)
    }

    const posthogUrl = `${context.api.getProjectBaseUrl(projectId)}/insights/${insightResult.data.short_id}`
    const queryInfo = analyzeQuery(insightResult.data.query)

    // Format results based on the query type
    // For trends/funnel, pass the inner query (TrendsQuery/FunnelsQuery) directly
    // The UI app infers the visualization type from the data structure
    if (queryInfo.visualization === 'trends' || queryInfo.visualization === 'funnel') {
        return withPostHogUrl(
            {
                query: queryInfo.innerQuery || insightResult.data.query,
                insight: {
                    url: posthogUrl,
                    ...insightResult.data,
                },
                results: queryResult.data.results,
            },
            posthogUrl
        )
    }

    // HogQL/table results have columns and results arrays
    return withPostHogUrl(
        {
            query: insightResult.data.query,
            insight: {
                url: posthogUrl,
                ...insightResult.data,
            },
            results: {
                columns: queryResult.data.columns || [],
                results: queryResult.data.results || [],
            },
        },
        posthogUrl
    )
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('query-results', {
        name: 'insight-query',
        schema,
        handler: queryHandler,
    })
