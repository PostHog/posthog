import { InsightQueryInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = InsightQueryInputSchema

type Params = z.infer<typeof schema>

export const queryHandler = async (context: Context, params: Params) => {
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

    const responseData = {
        insight: {
            url: `${context.api.getProjectBaseUrl(projectId)}/insights/${insightResult.data.short_id}`,
            ...insightResult.data,
        },
        results: queryResult.data.results,
    }

    return { content: [{ type: 'text', text: JSON.stringify(responseData) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insight-query',
    schema,
    handler: queryHandler,
})

export default tool
