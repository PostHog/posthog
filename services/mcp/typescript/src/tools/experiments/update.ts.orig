

import { ExperimentUpdateTransformSchema } from '@/schema/experiments'
import { ExperimentUpdateSchema } from '@/schema/tool-inputs'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context, Tool, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

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

    const experimentWithUrl = {
        ...updateResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/experiments/${updateResult.data.id}`,
    }

    return {
        content: [{ type: 'text', text: formatResponse(experimentWithUrl) }],
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
})

export default tool
