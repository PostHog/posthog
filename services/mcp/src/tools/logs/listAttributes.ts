import type { z } from 'zod'

import { LogsListAttributesInputSchema } from '@/schema/logs'
import type { Context, ToolBase } from '@/tools/types'

const schema = LogsListAttributesInputSchema

type Params = z.infer<typeof schema>

type Result = { results: unknown; count: unknown }

export const logsListAttributesHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const attributesResult = await context.api.logs({ projectId }).attributes({ params })
    if (!attributesResult.success) {
        throw new Error(`Failed to list log attributes: ${attributesResult.error.message}`)
    }

    return {
        results: attributesResult.data.results,
        count: attributesResult.data.count,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'logs-list-attributes',
    schema,
    handler: logsListAttributesHandler,
})

export default tool
