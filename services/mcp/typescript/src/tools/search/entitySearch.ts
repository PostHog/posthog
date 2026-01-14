import type { z } from 'zod'

import type { SearchableEntity, SearchResult } from '@/api/client'
import { EntitySearchSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EntitySearchSchema

type Params = z.infer<typeof schema>

// Map entity types to their URL paths in PostHog
const ENTITY_URL_PATHS: Record<string, string> = {
    insight: 'insights',
    dashboard: 'dashboard',
    experiment: 'experiments',
    feature_flag: 'feature_flags',
    notebook: 'notebooks',
    action: 'data-management/actions',
    cohort: 'cohorts',
    event_definition: 'data-management/events',
    survey: 'surveys',
}

export const entitySearchHandler: ToolBase<typeof schema>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.search({ projectId }).query({
        query: params.query,
        entities: params.entities as SearchableEntity[] | undefined,
    })

    if (!result.success) {
        throw new Error(`Failed to search entities: ${result.error.message}`)
    }

    // Enrich results with URLs
    const resultsWithUrls = result.data.results.map((item: SearchResult) => {
        const urlPath = ENTITY_URL_PATHS[item.type] || item.type
        return {
            ...item,
            url: `${context.api.getProjectBaseUrl(projectId)}/${urlPath}/${item.result_id}`,
        }
    })

    return {
        results: resultsWithUrls,
        counts: result.data.counts,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'entity-search',
    schema,
    handler: entitySearchHandler,
})

export default tool
