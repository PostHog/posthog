import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import type { HogQLQuery } from '@/schema/query'
import { QueryRunInputSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { analyzeQuery } from '../shared'
import { extractHogQLMetadata, formatHogQLMetadataForAgent } from './hogql-error-format'

const schema = QueryRunInputSchema

type Params = z.infer<typeof schema>

type Result = WithPostHogUrl<{ query: unknown; results: unknown }>

/** HogQL from MCP must carry tags.productKey or Django DEBUG raises UntaggedQueryError on sync_execute. */
function defaultHogqlProductKey(sql: string): string {
    if (/\btrace_spans\b/i.test(sql)) {
        return 'tracing'
    }
    if (/\blogs\b/i.test(sql)) {
        return 'logs'
    }
    return 'platform_and_support'
}

function withDefaultTagsOnHogqlNode<Q extends HogQLQuery>(node: Q): Q {
    if (node.tags?.productKey) {
        return node
    }
    return {
        ...node,
        tags: {
            ...node.tags,
            productKey: defaultHogqlProductKey(node.query),
            name: node.tags?.name ?? 'mcp_query_run',
        },
    }
}

function withDefaultHogqlTags(query: Params['query']): Params['query'] {
    if (query.kind === 'HogQLQuery') {
        return withDefaultTagsOnHogqlNode(query)
    }
    if (query.kind === 'DataVisualizationNode') {
        return {
            ...query,
            source: withDefaultTagsOnHogqlNode(query.source),
        }
    }
    return query
}

export const queryRunHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const query = withDefaultHogqlTags(params.query)

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
