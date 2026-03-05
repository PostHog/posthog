import type { z } from 'zod'

import { EXPERIMENT_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { ExperimentUpdateTransformSchema } from '@/schema/experiments'
import { ExperimentUpdateSchema } from '@/schema/tool-inputs'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context, Tool, ToolBase } from '@/tools/types'

const schema = ExperimentUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { experimentId, data } = params
    const projectId = await context.stateManager.getProjectId()

    // Transform the tool input to API payload format
    const apiPayload = ExperimentUpdateTransformSchema.parse(data)

    const updateResult = await context.api.experiments({ projectId }).update({
        experimentId,
        updateData: apiPayload,
    })

    if (!updateResult.success) {
        throw new Error(`Failed to update experiment: ${updateResult.error.message}`)
    }

    return {
        ...updateResult.data,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/experiments/${updateResult.data.id}`,
    }
}

const definition = getToolDefinition('experiment-update')

const tool = (): Tool<typeof schema> => ({
    name: 'experiment-update',
    title: definition.title,
    description: definition.description,
    schema,
    handler: updateHandler,
    scopes: ['experiments:write'],
    annotations: {
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
        readOnlyHint: false,
    },
    _meta: {
        ui: {
            resourceUri: EXPERIMENT_RESOURCE_URI,
        },
    },
})

export default tool
