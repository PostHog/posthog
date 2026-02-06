import type { z } from 'zod'

import { EventDefinitionUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EventDefinitionUpdateSchema

type Params = z.infer<typeof schema>

export const updateEventDefinitionHandler: ToolBase<typeof schema>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.projects().updateEventDefinition({
        projectId,
        eventName: params.eventName,
        data: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to update event definition: ${result.error.message}`)
    }

    return {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/events/${encodeURIComponent(result.data.name)}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'event-definition-update',
    schema,
    handler: updateEventDefinitionHandler,
})

export default tool
