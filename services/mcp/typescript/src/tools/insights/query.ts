import type { z } from 'zod'

import { QUERY_VISUALIZER_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { InsightQueryInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = InsightQueryInputSchema

type Params = z.infer<typeof schema>

export const queryHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
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

    const responseData = {
        query: insightResult.data.query,
        insight: {
            url: posthogUrl,
            ...insightResult.data,
        },
        results: queryResult.data.results,
        _posthogUrl: posthogUrl,
    }

    return responseData
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insight-query',
    schema,
    handler: queryHandler,
    _meta: {
        ui: {
            resourceUri: QUERY_VISUALIZER_RESOURCE_URI,
        },
    },
})

export default tool
