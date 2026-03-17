import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import { QueryRunInputSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { analyzeQuery } from '../shared'

const schema = QueryRunInputSchema

type Params = z.infer<typeof schema>

type Result = WithPostHogUrl<{ query: unknown; results: unknown }>

export const queryRunHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const { query } = params

    const projectId = await context.stateManager.getProjectId()

    const queryResult = await context.api.insights({ projectId }).query({
        query: query,
    })

    if (!queryResult.success) {
        throw new Error(`Failed to query insight: ${queryResult.error.message}`)
    }

    const baseUrl = context.api.getProjectBaseUrl(projectId)
    const queryParam = encodeURIComponent(JSON.stringify(query))
    const posthogUrl = `${baseUrl}/insights/new?q=${queryParam}`

    const queryInfo = analyzeQuery(query)

    // Format results based on the query type
    // TrendsQuery, FunnelsQuery, and PathsQuery return results directly as an array
    // HogQLQuery returns { results: [...], columns: [...] }
    // The UI app infers the visualization type from the data structure
    if (
        queryInfo.visualization === 'trends' ||
        queryInfo.visualization === 'funnel' ||
        queryInfo.visualization === 'paths'
    ) {
        return withPostHogUrl(
            {
                query: queryInfo.innerQuery || query,
                results: queryResult.data.results,
            },
            posthogUrl
        )
    }

    // HogQL/table results have columns and results arrays
    return withPostHogUrl(
        {
            query,
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
        name: 'query-run',
        schema,
        handler: queryRunHandler,
    })
