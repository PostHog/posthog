import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import type { Experiment } from '@/schema/experiments'
import { ExperimentUpdateTransformSchema } from '@/schema/experiments'
import { ExperimentUpdateSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context, Tool } from '@/tools/types'

const schema = ExperimentUpdateSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<Experiment>

export const updateHandler: Tool<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
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

    return withPostHogUrl(
        updateResult.data,
        `${context.api.getProjectBaseUrl(projectId)}/experiments/${updateResult.data.id}`
    )
}

const definition = getToolDefinition('experiment-update')

export default (): Tool<typeof schema, Result> =>
    withUiApp('experiment', {
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
