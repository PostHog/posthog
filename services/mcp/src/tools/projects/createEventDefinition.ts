import type { z } from 'zod'

import type { ApiEventDefinition } from '@/schema/api'
import { EventDefinitionCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EventDefinitionCreateSchema

type Params = z.infer<typeof schema>

type Result = ApiEventDefinition & { url: string }

export const createEventDefinitionHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.projects().createEventDefinition({
        projectId,
        eventName: params.eventName,
        data: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to create event definition: ${result.error.message}`)
    }

    return {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/events/${encodeURIComponent(result.data.name)}`,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'event-definition-create',
    schema,
    handler: createEventDefinitionHandler,
})

export default tool
