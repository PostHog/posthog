import type { z } from 'zod'

import { LogsListAttributeValuesInputSchema } from '@/schema/logs'
import type { Context, ToolBase } from '@/tools/types'

const schema = LogsListAttributeValuesInputSchema

type Params = z.infer<typeof schema>

export const logsListAttributeValuesHandler: ToolBase<typeof schema>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const valuesResult = await context.api.logs({ projectId }).values({ params })
    if (!valuesResult.success) {
        throw new Error(`Failed to list attribute values: ${valuesResult.error.message}`)
    }

    return valuesResult.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'logs-list-attribute-values',
    schema,
    handler: logsListAttributeValuesHandler,
})

export default tool
