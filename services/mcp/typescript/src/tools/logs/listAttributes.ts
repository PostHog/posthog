import type { z } from 'zod'

import { LogsListAttributesInputSchema } from '@/schema/logs'
import type { Context, ToolBase } from '@/tools/types'

const schema = LogsListAttributesInputSchema

type Params = z.infer<typeof schema>

export const logsListAttributesHandler: ToolBase<typeof schema>['handler'] = async (
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

const tool = (): ToolBase<typeof schema> => ({
    name: 'logs-list-attributes',
    schema,
    handler: logsListAttributesHandler,
})

export default tool
