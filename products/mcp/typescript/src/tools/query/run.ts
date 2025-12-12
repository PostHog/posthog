import type { z } from 'zod'

import { QueryRunInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

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

    return queryResult.data.results
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'query-run',
    schema,
    handler: queryRunHandler,
})

export default tool
