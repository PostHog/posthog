import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import { QueryRunInputSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { analyzeQuery } from '../shared'
import { extractHogQLMetadata, formatHogQLMetadataForAgent } from './hogql-error-format'

const schema = QueryRunInputSchema

type Params = z.infer<typeof schema>

type DataWarehouseSyncWarning = {
    table_name: string
    schema_name: string
    source_type: string
    status: string
    message: string
}

type Result = WithPostHogUrl<{ query: unknown; results: unknown; warnings?: DataWarehouseSyncWarning[] }>

export const queryRunHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const { query } = params

    const projectId = await context.stateManager.getProjectId()

    const queryResult = await context.api.insights({ projectId }).query({
        query: query,
    })

    if (!queryResult.success) {
        const metadata = extractHogQLMetadata(queryResult.error)
        const metadataBlock = formatHogQLMetadataForAgent(metadata)
        const suffix = metadataBlock ? `\n\n${metadataBlock}` : ''
        throw new Error(`Failed to query insight: ${queryResult.error.message}${suffix}`)
    }

    const queryParam = encodeURIComponent(JSON.stringify(query))
    const path = `/insights/new#q=${queryParam}`

    const queryInfo = analyzeQuery(query)

    // Format results based on the query type
    // TrendsQuery, FunnelsQuery, and PathsQuery return results directly as an array
    // HogQLQuery returns { results: [...], columns: [...] }
    // The UI app infers the visualization type from the data structure
    const warnings = queryResult.data.warnings

    if (
        queryInfo.visualization === 'trends' ||
        queryInfo.visualization === 'funnel' ||
        queryInfo.visualization === 'paths'
    ) {
        return withPostHogUrl(
            context,
            {
                query: queryInfo.innerQuery || query,
                results: queryResult.data.results,
                ...(warnings && warnings.length > 0 ? { warnings } : {}),
            },
            path
        )
    }

    // HogQL/table results have columns and results arrays
    return withPostHogUrl(
        context,
        {
            query,
            results: {
                columns: queryResult.data.columns || [],
                results: queryResult.data.results || [],
            },
            ...(warnings && warnings.length > 0 ? { warnings } : {}),
        },
        path
    )
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('query-results', {
        name: 'query-run',
        schema,
        handler: queryRunHandler,
    })
