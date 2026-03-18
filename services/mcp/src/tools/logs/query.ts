import type { z } from 'zod'

import { LogsQueryInputSchema } from '@/schema/logs'
import type { Context, ToolBase } from '@/tools/types'

const schema = LogsQueryInputSchema

type Params = z.infer<typeof schema>

type Result = { results: unknown; hasMore: boolean; nextCursor: unknown }

export const logsQueryHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const logsResult = await context.api.logs({ projectId }).query({ params })
    if (!logsResult.success) {
        throw new Error(`Failed to query logs: ${logsResult.error.message}`)
    }

    return {
        results: logsResult.data.results,
        hasMore: logsResult.data.hasMore,
        nextCursor: logsResult.data.nextCursor,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'logs-query',
    schema,
    handler: logsQueryHandler,
})

export default tool
