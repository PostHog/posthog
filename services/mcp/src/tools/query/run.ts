import type { z } from 'zod'

import { QUERY_RESULTS_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { QueryRunInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { analyzeQuery } from '../shared'

const schema = QueryRunInputSchema

type Params = z.infer<typeof schema>

export const queryRunHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
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
    // TrendsQuery and FunnelsQuery return results directly as an array
    // HogQLQuery returns { results: [...], columns: [...] }
    // The UI app infers the visualization type from the data structure
    if (queryInfo.visualization === 'trends' || queryInfo.visualization === 'funnel') {
        return {
            query: queryInfo.innerQuery || query,
            results: queryResult.data.results,
            _posthogUrl: posthogUrl,
        }
    }

    // HogQL/table results have columns and results arrays
    return {
        query,
        results: {
            columns: queryResult.data.columns || [],
            results: queryResult.data.results || [],
        },
        _posthogUrl: posthogUrl,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'query-run',
    schema,
    handler: queryRunHandler,
    _meta: {
        ui: {
            resourceUri: QUERY_RESULTS_RESOURCE_URI,
        },
    },
})

export default tool
